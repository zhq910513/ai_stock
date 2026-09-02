from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic
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
SESSION_STORE: dict[str, dict[str, str]] = {}
ADMIN_DASHBOARD_REFRESH_SECONDS = 300
ADMIN_DASHBOARD_LIMIT = 1000

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
TBOARD_DEFAULT_HIDDEN_STATUSES = {"stopped"}
TBOARD_DAY2_WINDOW_END = time(10, 30)
TBOARD_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _backend_proxy_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_BACKEND_TIMEOUT_SECONDS", "6.0"))


def _source_preflight_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_PREFLIGHT_TIMEOUT_SECONDS", "6.0"))


def _admin_dashboard_timeout_seconds() -> float:
    configured = os.getenv("SHENCE_FRONTEND_ADMIN_DASHBOARD_TIMEOUT_SECONDS")
    if configured:
        return float(configured)
    return max(_backend_proxy_timeout_seconds(), 90.0)


def _admin_dashboard_cache_ttl_seconds() -> float:
    configured = os.getenv("SHENCE_FRONTEND_ADMIN_DASHBOARD_CACHE_TTL_SECONDS", "10.0")
    return max(0.0, float(configured))


_ADMIN_DASHBOARD_PAYLOAD_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_ADMIN_DASHBOARD_PAYLOAD_INFLIGHT: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}
_ADMIN_DASHBOARD_PAYLOAD_LOCK = asyncio.Lock()


def _admin_payload_cacheable(payloads: dict[str, Any]) -> bool:
    return not any(isinstance(value, Exception) for value in payloads.values())


async def _cached_admin_payloads(kind: str, trade_date: date, loader) -> dict[str, Any]:
    key = (kind, trade_date.isoformat())
    ttl_seconds = _admin_dashboard_cache_ttl_seconds()
    now = monotonic()
    async with _ADMIN_DASHBOARD_PAYLOAD_LOCK:
        cached = _ADMIN_DASHBOARD_PAYLOAD_CACHE.get(key)
        if ttl_seconds > 0 and cached and cached[0] > now:
            return cached[1]
        task = _ADMIN_DASHBOARD_PAYLOAD_INFLIGHT.get(key)
        if task is None:
            task = asyncio.create_task(loader())
            _ADMIN_DASHBOARD_PAYLOAD_INFLIGHT[key] = task
    try:
        payloads = await task
    finally:
        async with _ADMIN_DASHBOARD_PAYLOAD_LOCK:
            if _ADMIN_DASHBOARD_PAYLOAD_INFLIGHT.get(key) is task:
                _ADMIN_DASHBOARD_PAYLOAD_INFLIGHT.pop(key, None)
    if ttl_seconds > 0 and _admin_payload_cacheable(payloads):
        async with _ADMIN_DASHBOARD_PAYLOAD_LOCK:
            _ADMIN_DASHBOARD_PAYLOAD_CACHE[key] = (monotonic() + ttl_seconds, payloads)
    return payloads

def _tboard_compact_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_TBOARD_COMPACT_TIMEOUT_SECONDS", "30.0"))


def _hot_model_list_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_HOT_MODEL_LIST_TIMEOUT_SECONDS", "30.0"))


def _frontend_accounts() -> dict[str, dict[str, str]]:
    legacy_username = os.getenv("SHENCE_FRONTEND_USERNAME")
    admin_username = os.getenv("SHENCE_FRONTEND_ADMIN_USERNAME") or (legacy_username if legacy_username == "admin" else "admin")
    admin_password = os.getenv("SHENCE_FRONTEND_ADMIN_PASSWORD") or (
        os.getenv("SHENCE_FRONTEND_PASSWORD", "admin") if legacy_username == admin_username else "admin"
    )
    accounts: dict[str, dict[str, str]] = {
        admin_username: {
            "username": admin_username,
            "role": "admin",
            "password": admin_password,
            "password_sha256": os.getenv("SHENCE_FRONTEND_ADMIN_PASSWORD_SHA256", ""),
        }
    }
    legacy_username = os.getenv("SHENCE_FRONTEND_USERNAME")
    if legacy_username and legacy_username not in accounts:
        accounts[legacy_username] = {
            "username": legacy_username,
            "role": os.getenv("SHENCE_FRONTEND_ROLE", "operator"),
            "password": os.getenv("SHENCE_FRONTEND_PASSWORD", "admin"),
            "password_sha256": os.getenv("SHENCE_FRONTEND_PASSWORD_SHA256", ""),
        }
    return accounts


def _public_user(account: dict[str, str]) -> dict[str, str]:
    return {"username": account.get("username", ""), "role": account.get("role", "viewer")}


def _frontend_user() -> dict[str, str]:
    accounts = _frontend_accounts()
    legacy_username = os.getenv("SHENCE_FRONTEND_USERNAME")
    admin_username = os.getenv("SHENCE_FRONTEND_ADMIN_USERNAME") or (legacy_username if legacy_username == "admin" else "admin")
    account = accounts.get(admin_username) or next(iter(accounts.values()))
    return _public_user(account)


def _password_matches(password: str, account: dict[str, str]) -> bool:
    expected_hash = str(account.get("password_sha256") or "").strip().lower()
    if expected_hash:
        actual_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual_hash, expected_hash)
    return hmac.compare_digest(password, str(account.get("password") or ""))


def _authenticate_user(username: str, password: str) -> dict[str, str] | None:
    account = _frontend_accounts().get(username)
    if not account or not _password_matches(password, account):
        return None
    return _public_user(account)


def _session_user(request: Request) -> dict[str, str] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return SESSION_STORE.get(token)


def _is_authenticated(request: Request) -> bool:
    return _session_user(request) is not None


def _require_authenticated(request: Request) -> dict[str, str]:
    user = _session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    return user


def _require_admin(request: Request) -> dict[str, str]:
    user = _require_authenticated(request)
    if str(user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


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
    local_defaults = {
        "source": "http://127.0.0.1:8041",
        "scheduler": "http://127.0.0.1:8023",
        "data-inspector": "http://127.0.0.1:8025",
        "hot": "http://127.0.0.1:8031",
        "memory": "http://127.0.0.1:8032",
        "ambush": "http://127.0.0.1:8033",
        "tboard": "http://127.0.0.1:8035",
        "research-service": "http://127.0.0.1:8029",
        "research": "http://127.0.0.1:8028",
    }
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
        local_url = local_defaults.get(service)
        if local_url and local_url.rstrip("/") not in urls:
            urls.append(local_url.rstrip("/"))
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
    return _tboard_market_now().date()


def _tboard_market_now() -> datetime:
    return datetime.now(TBOARD_MARKET_TIMEZONE)


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


def _next_weekday(day_value: date) -> date:
    next_day = day_value + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day


def _tboard_day2_window_elapsed(item: dict[str, Any]) -> bool:
    expected_day2 = _date_key(item.get("day2_trade_date"))
    if expected_day2 is None:
        day1_trade_date = _date_key(item.get("day1_trade_date"))
        if day1_trade_date is not None:
            expected_day2 = _next_weekday(day1_trade_date)
    if expected_day2 is None:
        return False
    now = _tboard_market_now()
    today = now.date()
    if today.weekday() >= 5:
        return False
    if today > expected_day2:
        return True
    if today < expected_day2:
        return False
    return now.time() >= TBOARD_DAY2_WINDOW_END


def _tboard_should_hide_default(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    status = str(item.get("observation_status") or "").lower()
    if status in TBOARD_DEFAULT_HIDDEN_STATUSES:
        return True
    return status == "data_wait" and _tboard_day2_window_elapsed(item)


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
            if include_stale_stopped or not _tboard_should_hide_default(item)
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
        "float_market_cap_missing": "流通市值缺失，无法判断",
        "data_blocked": "关键数据缺失，等待补全",
    }
    key = str(reason or "").strip()
    return labels.get(key, "关键条件未通过" if key else "条件待确认")


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
            main_reason = "开盘涨停但盘中开板或收盘回封结构未同时满足严格 T 字板条件"
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
            if response.status_code == 404:
                break
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


def _dashboard_market_today() -> date:
    return datetime.now(TBOARD_MARKET_TIMEZONE).date()


def _dashboard_trade_date(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid trade_date") from exc
    return _dashboard_market_today()


def _payload_rows(payload: Any, key: str = "rows") -> list[dict[str, Any]]:
    if isinstance(payload, Exception):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
        items = payload.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _payload_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) and not isinstance(payload, Exception) else {}


def _payload_available(payload: Any) -> bool:
    return isinstance(payload, dict) and not isinstance(payload, Exception)


def _admin_upstream_status(payloads: dict[str, Any]) -> dict[str, dict[str, str]]:
    status: dict[str, dict[str, str]] = {}
    for key, value in payloads.items():
        if isinstance(value, Exception):
            message = str(getattr(value, "detail", value))
            if key == "inspection_latest" and ("404" in message or "No data inspection run found" in message):
                status[key] = {"status": "missing", "message": "完整性验收未生成"}
            else:
                status[key] = {"status": "unavailable", "message": message}
        else:
            status[key] = {"status": "ok", "message": "read"}
    return status

def _admin_inspection_coverage(payloads: dict[str, Any], trade_date: date) -> dict[str, Any]:
    latest_payload = payloads.get("inspection_latest")
    latest = _payload_dict(latest_payload)
    target_day = trade_date.isoformat()
    if latest:
        contract = latest.get("run_contract_json") if isinstance(latest.get("run_contract_json"), dict) else {}
        time_semantics = contract.get("time_semantics") if isinstance(contract.get("time_semantics"), dict) else {}
        run_day = str(
            latest.get("as_of_trading_day")
            or latest.get("trading_day")
            or time_semantics.get("as_of_trading_day")
            or ""
        )[:10]
        covered = not run_day or run_day == target_day
        status = str(latest.get("status") or "read")
        return {
            "covered": covered,
            "status": status if covered else "stale",
            "label": "今日数据已验收" if covered else "完整性验收未生成",
            "message": "完整性验收已生成。" if covered else f"当前读到的是 {run_day or '-'} 的验收结果，还不是 {target_day}。",
            "run_id": latest.get("run_id"),
            "as_of_trading_day": run_day or target_day,
            "finished_at": latest.get("finished_at"),
        }
    detail = ""
    if isinstance(latest_payload, Exception):
        detail = str(getattr(latest_payload, "detail", latest_payload))
    missing_for_day = "404" in detail or "No data inspection run found" in detail
    return {
        "covered": False,
        "status": "missing_for_trade_date" if missing_for_day else "unavailable",
        "label": "完整性验收未生成",
        "message": "完整性验收还未生成，任务完成度仍以调度账本和数据产出为准。" if missing_for_day else (detail or "数据巡检暂时不可读。"),
        "run_id": None,
        "as_of_trading_day": None,
        "finished_at": None,
    }
def _dashboard_time_key(value: Any) -> tuple[int, float, str]:
    return _tboard_time_order_key(value)


def _dashboard_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TBOARD_MARKET_TIMEZONE)
    return parsed.astimezone(TBOARD_MARKET_TIMEZONE)


def _admin_task_has_explicit_lifecycle(item: dict[str, Any]) -> bool:
    request_body = item.get("request_body") if isinstance(item.get("request_body"), dict) else {}
    context = request_body.get("orchestration_context") if isinstance(request_body.get("orchestration_context"), dict) else {}
    return bool(
        context.get("lifecycle_expires_at_local")
        or context.get("lifecycle_expires_at")
        or item.get("lifecycle_expires_at_local")
        or item.get("lifecycle_expires_at")
    )


def _admin_task_lifecycle_expired(item: dict[str, Any], now: datetime | None = None) -> bool:
    now_dt = now or datetime.now(TBOARD_MARKET_TIMEZONE)
    request_body = item.get("request_body") if isinstance(item.get("request_body"), dict) else {}
    context = request_body.get("orchestration_context") if isinstance(request_body.get("orchestration_context"), dict) else {}
    explicit_expiry = _dashboard_datetime(
        context.get("lifecycle_expires_at_local")
        or context.get("lifecycle_expires_at")
        or item.get("lifecycle_expires_at_local")
        or item.get("lifecycle_expires_at")
    )
    if explicit_expiry is not None:
        return now_dt > explicit_expiry

    scheduled_at = _dashboard_datetime(item.get("scheduled_at_local") or item.get("scheduled_at"))
    if scheduled_at is None:
        return False
    group = str(item.get("schedule_group") or request_body.get("schedule_group") or "").lower()
    if group in {"minute_auction", "minute_intraday", "t_relay_day2_window"}:
        expiry = scheduled_at + timedelta(minutes=10)
    elif group == "daily_preopen":
        expiry = datetime.combine(scheduled_at.date(), time(23, 59, 59), tzinfo=TBOARD_MARKET_TIMEZONE)
    elif group == "daily_preopen_paid_probability_guard":
        expiry = scheduled_at + timedelta(minutes=30)
    elif group in {"t_relay_day1_window", "t_relay_day1_candidate_facts"}:
        expiry = scheduled_at + timedelta(minutes=20)
    elif group in {"daily_close", "daily_research_context"}:
        expiry = scheduled_at + timedelta(hours=2)
    elif group == "daily_close_paid_probability":
        expiry = scheduled_at + timedelta(hours=4)
    else:
        expiry = datetime.combine(scheduled_at.date(), time(23, 59, 59), tzinfo=TBOARD_MARKET_TIMEZONE)
    return now_dt > expiry


def _latest_by_time(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_key: tuple[int, float, str] = (0, 0.0, "")
    for row in rows:
        for field in fields:
            key = _dashboard_time_key(row.get(field))
            if best is None or key > best_key:
                best = row
                best_key = key
    return best


def _latest_rows_by_table(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        table = str(row.get("source_table_name") or "").strip()
        if table:
            grouped.setdefault(table, []).append(row)
    return {table: latest for table, table_rows in grouped.items() if (latest := _latest_by_time(table_rows, fields)) is not None}


def _dashboard_table_label(source_table_name: str) -> str:
    labels = {
        "source.trade_calendar_v1": "交易日历",
        "source.stock_master_v1": "股票主数据",
        "source.stock_universe_daily_v1": "今日股票池",
        "source.trade_status_v1": "交易状态",
        "source.daily_bar_v1": "日线行情",
        "source.adjusted_daily_bar_v1": "复权日线",
        "source.adjustment_factor_v1": "复权因子",
        "source.limit_price_v1": "涨跌停价格",
        "source.limit_event_v1": "涨跌停事件",
        "source.ths_paid_limit_up_probability_v1": "同花顺次日概率",
        "source.stock_moneyflow_daily_v1": "个股资金流",
        "source.index_daily_bar_v1": "指数日线",
        "source.event_news_v1": "新闻事件",
        "source.stock_board_membership_v1": "板块成分",
        "source.board_daily_bar_v1": "板块日线",
        "source.realtime_quote_v1": "实时行情快照",
        "source.minute_bar_v1": "分钟行情",
        "source.trade_tick_v1": "逐笔成交",
        "source.auction_snapshot_v1": "集合竞价快照",
    }
    return labels.get(source_table_name, source_table_name)


def _priority_rank(priority: Any) -> int:
    text = str(priority or "").upper()
    if "P0" in text:
        return 0
    if "P1" in text:
        return 1
    if "P2" in text:
        return 2
    return 9


def _best_priority(values: list[Any]) -> str:
    ordered = sorted((str(item or "").upper() for item in values if item), key=_priority_rank)
    return ordered[0] if ordered else "UNKNOWN"


def _asset_repairability(source_table_name: str, fields: list[str], slas: list[dict[str, Any]], repair_routes: list[dict[str, Any]]) -> dict[str, str]:
    window_limited_tables = {
        "source.realtime_quote_v1",
        "source.minute_bar_v1",
        "source.trade_tick_v1",
        "source.auction_snapshot_v1",
        "source.ths_paid_limit_up_probability_v1",
    }
    table_slas = [item for item in slas if item.get("source_table_name") == source_table_name]
    frequencies = {str(item.get("frequency") or "").lower() for item in table_slas}
    has_route = any(item.get("source_table_name") == source_table_name for item in repair_routes)
    has_backup = any(item.get("source_table_name") == source_table_name and item.get("backup_provider") for item in repair_routes)
    if source_table_name in window_limited_tables or frequencies & {"intraday_snapshot", "intraday_tick", "minute"}:
        return {
            "code": "non_repairable_after_window",
            "label": "窗口过期不可补",
            "reason": "依赖盘中快照、逐笔、竞价或付费时效窗口；错过窗口后不能用后验数据冒充当时事实。",
        }
    if has_route or has_backup:
        return {
            "code": "repairable_after_expiry",
            "label": "可过期补全",
            "reason": "存在正式补采路径、备用 provider 或 source build 重建路径。",
        }
    return {
        "code": "contract_pending",
        "label": "补全能力待确认",
        "reason": "当前只读合同未暴露可审计补采路径，缺失时必须保持缺口。",
    }


def _asset_lifecycle(trade_date: date, slas: list[dict[str, Any]]) -> dict[str, str | None]:
    if not slas:
        return {"code": "contract_only", "label": "按合同观察", "expected_at": None, "latest_acceptable_at": None}
    expected_times = [str(item.get("expected_available_time") or "") for item in slas if item.get("expected_available_time")]
    latest_limits = [str(item.get("latest_acceptable_time") or "") for item in slas if item.get("latest_acceptable_time")]
    earliest_expected = min(expected_times) if expected_times else None
    latest_limit = max(latest_limits) if latest_limits else None
    now = datetime.now(TBOARD_MARKET_TIMEZONE)
    if latest_limit:
        latest_dt = datetime.combine(trade_date, time.fromisoformat(latest_limit)).replace(tzinfo=TBOARD_MARKET_TIMEZONE)
        if now < latest_dt:
            label = "等待采集窗口" if now.date() <= trade_date else "已错过采集窗口"
            code = "not_due" if now.date() <= trade_date else "past_window"
        else:
            label = "已过最晚时间"
            code = "after_deadline"
    else:
        label = "按合同观察"
        code = "contract_only"
    return {"code": code, "label": label, "expected_at": earliest_expected, "latest_acceptable_at": latest_limit}


def _gap_matches_table(gap: dict[str, Any], source_table_name: str) -> bool:
    explicit_table = gap.get("target_table") or gap.get("source_table_name")
    if explicit_table:
        return str(explicit_table) == source_table_name
    try:
        text = json.dumps(gap, ensure_ascii=False)
    except TypeError:
        text = str(gap)
    return source_table_name in text


def _gaps_for_table(gaps: list[dict[str, Any]], source_table_name: str) -> list[dict[str, Any]]:
    return [gap for gap in gaps if _gap_matches_table(gap, source_table_name)]


def _gap_summary(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    severities = [str(item.get("severity") or "").upper() for item in gaps]
    return {
        "count": len(gaps),
        "p0_count": sum(1 for item in severities if item == "P0"),
        "p1_count": sum(1 for item in severities if item == "P1"),
        "top_codes": [str(item.get("gap_code") or item.get("gap_type") or item.get("domain_code") or "unknown") for item in gaps[:3]],
    }


def _queue_summary(queue_payload: Any) -> dict[str, Any]:
    rows = _payload_rows(queue_payload)
    totals = {
        "queued_count": sum(int(row.get("queued_count") or 0) for row in rows),
        "leased_count": sum(int(row.get("leased_count") or 0) for row in rows),
        "failed_count": sum(int(row.get("failed_count") or 0) for row in rows),
        "dead_letter_count": sum(int(row.get("dead_letter_count") or 0) for row in rows),
    }
    totals["active_count"] = totals["queued_count"] + totals["leased_count"]
    return {"rows": rows, **totals}


def _daily_fact_final_data_failed(daily_fact: dict[str, Any]) -> bool:
    status = str(daily_fact.get("data_asset_status") or "").lower()
    if bool(daily_fact.get("final_data_failed")) or status in {"failed", "data_failed", "build_failed", "coverage_insufficient"}:
        return True
    return int(daily_fact.get("build_failed_count") or 0) > 0


def _daily_fact_raw_audit_only(daily_fact: dict[str, Any]) -> bool:
    if _daily_fact_final_data_failed(daily_fact):
        return False
    status = str(daily_fact.get("data_asset_status") or "").lower()
    return bool(daily_fact.get("raw_failure_audit_only")) or status == "completed_with_provider_audit"


def _daily_fact_has_target_evidence(daily_fact: dict[str, Any]) -> bool:
    status = str(daily_fact.get("data_asset_status") or "").lower()
    if status == "coverage_insufficient" or bool(daily_fact.get("coverage_insufficient")):
        return False
    return int(daily_fact.get("source_row_count") or 0) > 0 or int(daily_fact.get("build_succeeded_count") or 0) > 0


def _daily_fact_has_completion_evidence(daily_fact: dict[str, Any]) -> bool:
    status = str(daily_fact.get("data_asset_status") or "").lower()
    return status in {"completed", "completed_with_provider_audit"}


def _daily_fact_expired_closed(daily_fact: dict[str, Any]) -> bool:
    if not daily_fact or _daily_fact_final_data_failed(daily_fact) or _daily_fact_has_target_evidence(daily_fact):
        return False
    status = str(daily_fact.get("data_asset_status") or "").lower()
    if status == "expired_closed":
        return True
    return (
        int(daily_fact.get("raw_cancelled_count") or 0) > 0
        and int(daily_fact.get("raw_active_count") or 0) == 0
        and int(daily_fact.get("raw_waiting_count") or 0) == 0
    )


def _daily_fact_collecting_or_waiting(daily_fact: dict[str, Any]) -> bool:
    if not daily_fact or _daily_fact_final_data_failed(daily_fact) or _daily_fact_has_target_evidence(daily_fact):
        return False
    return _daily_fact_has_open_raw_work(daily_fact)


def _daily_fact_has_open_raw_work(daily_fact: dict[str, Any]) -> bool:
    if not daily_fact or _daily_fact_final_data_failed(daily_fact):
        return False
    status = str(daily_fact.get("data_asset_status") or "").lower()
    if status in {"completed", "completed_with_provider_audit", "failed", "data_failed", "build_failed", "coverage_insufficient", "expired_closed"}:
        return False
    if status in {"collecting", "queued", "running", "pending", "waiting", "in_progress"}:
        return True
    return any(
        int(daily_fact.get(key) or 0) > 0
        for key in ("raw_active_count", "raw_waiting_count", "queued_count", "leased_count")
    )


def _daily_fact_collecting(daily_fact: dict[str, Any]) -> bool:
    status = str(daily_fact.get("data_asset_status") or "").lower()
    return status in {"collecting", "running", "in_progress"} or int(daily_fact.get("raw_active_count") or 0) > 0


_ADMIN_SOURCE_TASK_PROCESSED_STATUSES = {"completed", "success", "source_duplicate_skipped", "build_succeeded_target_check"}


def _admin_source_task_processed(status: str) -> bool:
    return str(status or "").lower() in _ADMIN_SOURCE_TASK_PROCESSED_STATUSES


def _admin_asset_rows(payloads: dict[str, Any], trade_date: date, inspection_coverage: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    requirements = _payload_rows(payloads.get("requirements"))
    freshness = _payload_rows(payloads.get("freshness_sla"))
    readiness = _payload_rows(payloads.get("readiness_matrix"))
    repair_routes = _payload_rows(payloads.get("repair_routes"))
    registry = _payload_dict(payloads.get("source_schedule_registry"))
    schedules = _payload_rows(registry.get("schedules") if registry else [])
    materialized = _payload_rows(payloads.get("source_schedule_materialized"), key="instances")
    gaps = _payload_rows(payloads.get("inspection_gaps"))
    build_results = _payload_rows(payloads.get("build_results"))
    build_triggers = _payload_rows(payloads.get("build_triggers"))
    latest_build = _latest_rows_by_table(build_results, ("finished_at", "started_at"))
    latest_trigger = _latest_rows_by_table(build_triggers, ("finished_at", "created_at"))
    source_daily_summary = _payload_dict(payloads.get("source_daily_summary"))
    source_daily_tables = {
        str(item.get("source_table_name") or ""): item
        for item in _payload_rows(source_daily_summary, key="tables")
        if str(item.get("source_table_name") or "")
    }

    tables = sorted(
        {
            *(str(item.get("source_table_name") or "").strip() for item in requirements),
            *(str(item.get("source_table_name") or "").strip() for item in freshness),
            *(str(item.get("source_table_name") or "").strip() for item in readiness),
            *(str(item.get("source_table_name") or "").strip() for item in schedules),
            *(str(item.get("source_table_name") or "").strip() for item in materialized),
        }
        - {""}
    )
    rows: list[dict[str, Any]] = []
    for table in tables:
        table_reqs = [item for item in requirements if item.get("source_table_name") == table]
        table_slas = [item for item in freshness if item.get("source_table_name") == table]
        table_ready = next((item for item in readiness if item.get("source_table_name") == table), {})
        table_schedules = [item for item in schedules if item.get("source_table_name") == table]
        table_instances = [item for item in materialized if item.get("source_table_name") == table]
        table_gaps = _gaps_for_table(gaps, table)
        gap_info = _gap_summary(table_gaps)
        fields = sorted({str(item.get("canonical_field_name") or "").strip() for item in table_reqs + table_slas if item.get("canonical_field_name")})
        priority = _best_priority([item.get("required_level") for item in table_reqs] + [item.get("priority") for item in table_schedules])
        repairability = _asset_repairability(table, fields, table_slas, repair_routes)
        lifecycle = _asset_lifecycle(trade_date, table_slas)
        build = latest_build.get(table)
        trigger = latest_trigger.get(table)
        daily_fact = source_daily_tables.get(table, {})
        raw_failed_count = int(daily_fact.get("raw_failed_count") or 0)
        build_failed_count = int(daily_fact.get("build_failed_count") or 0)
        source_row_count = int(daily_fact.get("source_row_count") or 0)
        build_succeeded_count = int(daily_fact.get("build_succeeded_count") or 0)
        final_data_failed = _daily_fact_final_data_failed(daily_fact)
        raw_failure_audit_only = _daily_fact_raw_audit_only(daily_fact)
        data_produced = _daily_fact_has_target_evidence(daily_fact)
        if final_data_failed:
            status = "data_failed"
            status_label = "数据产出失败"
        elif gap_info["count"]:
            if repairability["code"] == "non_repairable_after_window" and lifecycle["code"] == "after_deadline":
                status = "expired_unrepairable"
                status_label = "目标数据缺失，不可补"
            elif repairability["code"] == "repairable_after_expiry":
                status = "missing_repairable"
                status_label = "目标数据缺失，可补"
            else:
                status = "missing_unknown_repairability"
                status_label = "目标数据缺失，待确认"
        elif _daily_fact_expired_closed(daily_fact):
            status = "expired_closed"
            status_label = "过期已关闭"
        elif lifecycle["code"] == "not_due":
            status = "not_due"
            status_label = "未到抓取时间"
        elif data_produced:
            status = "no_known_gap"
            status_label = "已产出，有采集审计" if raw_failure_audit_only else "已产出"
        else:
            status = "awaiting_data_result"
            status_label = "等待数据结果"
        if status == "awaiting_data_result":
            known_missing = None
            known_completed = None
        elif status == "data_failed":
            known_missing = raw_failed_count + build_failed_count
            known_completed = source_row_count if source_row_count else None
        else:
            known_missing = int(gap_info["count"])
            known_completed = max(len(fields) - int(gap_info["count"]), 0) if fields else None
        rows.append(
            {
                "source_table_name": table,
                "asset_label": _dashboard_table_label(table),
                "priority": priority,
                "fields": fields,
                "required_field_count": len(fields),
                "known_completed_field_count": known_completed,
                "known_missing_field_count": known_missing,
                "used_by_models": sorted({model for item in table_reqs + table_slas for model in item.get("used_by_models", [])}),
                "schedule_count": len(table_schedules),
                "materialized_instance_count": len(table_instances),
                "status": status,
                "status_label": status_label,
                "lifecycle": lifecycle,
                "repairability": repairability,
                "readiness_status": table_ready.get("readiness_status"),
                "readiness_blocking_reasons": table_ready.get("blocking_reasons") or [],
                "gap_summary": gap_info,
                "daily_data_fact": daily_fact,
                "raw_cancelled_count": int(daily_fact.get("raw_cancelled_count") or 0),
                "data_asset_status": daily_fact.get("data_asset_status"),
                "final_data_failed": final_data_failed,
                "raw_failure_audit_only": raw_failure_audit_only,
                "raw_job_count": daily_fact.get("raw_job_count"),
                "raw_failed_count": raw_failed_count,
                "build_failed_count": build_failed_count,
                "daily_source_row_count": source_row_count,
                "latest_data_update_at": daily_fact.get("latest_source_available_at") or daily_fact.get("latest_build_finished_at") or daily_fact.get("latest_raw_updated_at"),
                "failure_samples": daily_fact.get("failure_samples") or [],
                "latest_build": None
                if not build
                else {
                    "status": build.get("status"),
                    "finished_at": build.get("finished_at"),
                    "raw_row_count": build.get("raw_row_count"),
                    "source_row_count": build.get("source_row_count"),
                    "lineage_row_count": build.get("lineage_row_count"),
                    "note": "构建成功只说明批次处理过；是否完成目标日期事实仍以巡检、缺口和目标行证据为准。",
                },
                "latest_build_trigger": None
                if not trigger
                else {
                    "status": trigger.get("status"),
                    "finished_at": trigger.get("finished_at"),
                    "fetch_batch_id": trigger.get("fetch_batch_id"),
                },
            }
        )
    return sorted(rows, key=lambda item: (_priority_rank(item["priority"]), item["source_table_name"]))


def _admin_data_summary(asset_rows: list[dict[str, Any]], payloads: dict[str, Any], inspection_coverage: dict[str, Any]) -> dict[str, Any]:
    queue = _queue_summary(payloads.get("queue_summary"))
    latest_run = _payload_dict(payloads.get("inspection_latest"))
    inspection_covered = bool(inspection_coverage.get("covered"))
    source_daily_summary = _payload_dict(payloads.get("source_daily_summary"))
    source_daily_counts = source_daily_summary.get("summary") if isinstance(source_daily_summary.get("summary"), dict) else {}
    missing_assets = [item for item in asset_rows if item["gap_summary"]["count"] or item["status"] == "data_failed"]
    due_assets = [item for item in asset_rows if item["status"] != "not_due"]
    completed_due_assets = [item for item in due_assets if item["status"] == "no_known_gap"]
    not_due_assets = [item for item in asset_rows if item["status"] == "not_due"]
    unknown_assets = [item for item in asset_rows if item["status"] == "awaiting_data_result"]
    unrepairable_missing = [item for item in missing_assets if item["repairability"]["code"] == "non_repairable_after_window"]
    repairable_missing = [item for item in missing_assets if item["repairability"]["code"] == "repairable_after_expiry"]
    return {
        "total_assets": len(asset_rows),
        "due_assets": len(due_assets),
        "completed_due_assets": len(completed_due_assets),
        "not_due_assets": len(not_due_assets),
        "awaiting_data_result_assets": len(unknown_assets),
        "inspection_unknown_assets": 0,
        "no_known_gap_assets": sum(1 for item in asset_rows if item["status"] == "no_known_gap"),
        "data_failed_assets": sum(1 for item in asset_rows if item["status"] == "data_failed"),
        "data_failed_table_count": int(source_daily_counts.get("data_failed_table_count") or 0),
        "raw_audit_warning_table_count": int(source_daily_counts.get("audit_warning_table_count") or 0),
        "raw_failed_jobs": int(source_daily_counts.get("raw_failed_jobs") or 0),
        "build_failed_results": int(source_daily_counts.get("build_failed_results") or 0),
        "source_row_count": int(source_daily_counts.get("source_row_count") or 0),
        "latest_data_update_at": source_daily_counts.get("latest_data_update_at"),
        "missing_assets": len(missing_assets),
        "repairable_missing_assets": len(repairable_missing),
        "unrepairable_missing_assets": len(unrepairable_missing),
        "p0_gap_count": int(latest_run.get("p0_gap_count") or 0) if inspection_covered and latest_run else None,
        "p1_gap_count": int(latest_run.get("p1_gap_count") or 0) if inspection_covered and latest_run else None,
        "latest_inspection_run_id": inspection_coverage.get("run_id"),
        "latest_inspection_status": inspection_coverage.get("status"),
        "latest_inspection_finished_at": inspection_coverage.get("finished_at"),
        "inspection_coverage": inspection_coverage,
        "queue": queue,
    }

def _admin_task_rows(payloads: dict[str, Any], inspection_coverage: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    scheduler_daily = _payload_dict(payloads.get("scheduler_daily_summary"))
    scheduler_rows = _payload_rows(scheduler_daily, key="tasks")
    requirements = _payload_rows(payloads.get("requirements"))
    freshness = _payload_rows(payloads.get("freshness_sla"))
    repair_routes = _payload_rows(payloads.get("repair_routes"))
    source_daily_payload = payloads.get("source_daily_summary")
    source_daily_available = _payload_available(source_daily_payload)
    source_daily = _payload_dict(source_daily_payload)
    source_daily_tables = {
        str(item.get("source_table_name") or ""): item
        for item in _payload_rows(source_daily, key="tables")
        if str(item.get("source_table_name") or "")
    }
    if scheduler_rows:
        rows: list[dict[str, Any]] = []
        for item in scheduler_rows:
            table = str(item.get("source_table_name") or "").strip()
            table_reqs = [row for row in requirements if row.get("source_table_name") == table]
            table_slas = [row for row in freshness if row.get("source_table_name") == table]
            fields = sorted({str(row.get("canonical_field_name") or "").strip() for row in table_reqs + table_slas if row.get("canonical_field_name")})
            repairability = _asset_repairability(table, fields, table_slas, repair_routes)
            request_body = item.get("request_body") if isinstance(item.get("request_body"), dict) else {}
            has_daily_fact = table in source_daily_tables
            daily_fact = source_daily_tables.get(table, {})
            execution_status = str(item.get("execution_status") or item.get("status") or "awaiting_dispatch")
            task_processed = _admin_source_task_processed(execution_status)
            final_data_failed = _daily_fact_final_data_failed(daily_fact)
            raw_failure_audit_only = _daily_fact_raw_audit_only(daily_fact)
            source_submitted_job_count = int(item.get("source_submitted_job_count") or 0)
            source_skipped_duplicate_count = int(item.get("source_skipped_duplicate_count") or 0)
            source_fetch_status = str(item.get("source_fetch_status") or "").strip()
            task_has_explicit_lifecycle = _admin_task_has_explicit_lifecycle(item)
            task_lifecycle_expired = _admin_task_lifecycle_expired(item)
            display_status = "completed" if task_processed else execution_status
            label_map = {
                "completed": "已完成",
                "not_due": "未到抓取时间",
                "collecting": "等待抓取/产出",
                "coverage_insufficient": "覆盖不足",
                "failed": "执行失败",
                "awaiting_dispatch": "待提交抓取",
                "awaiting_evidence": "等待数据结果",
                "expired_closed": "已过期关闭",
            }
            if final_data_failed and task_processed:
                display_status = "coverage_insufficient" if str(daily_fact.get("data_asset_status") or "").lower() == "coverage_insufficient" else ("build_failed" if int(daily_fact.get("build_failed_count") or 0) else "target_fact_missing")
            elif source_daily_available and not task_processed and task_lifecycle_expired and display_status not in {"not_due", "failed"}:
                display_status = "expired_closed"
            elif (
                source_daily_available
                and task_processed
                and task_lifecycle_expired
                and (not has_daily_fact or not _daily_fact_has_target_evidence(daily_fact))
                and (
                    task_has_explicit_lifecycle
                    or not _daily_fact_has_open_raw_work(daily_fact)
                    or repairability.get("code") != "non_repairable_after_window"
                )
            ):
                display_status = "expired_closed"
            elif task_processed and _daily_fact_expired_closed(daily_fact):
                display_status = "expired_closed"
            elif task_processed and not source_daily_available:
                display_status = "awaiting_evidence"
            elif task_processed and table and not has_daily_fact:
                display_status = "awaiting_evidence"
            elif task_processed and has_daily_fact:
                has_live_source_submission = source_submitted_job_count > 0 or source_fetch_status in {"queued", "leased", "running"}
                if has_live_source_submission and _daily_fact_has_open_raw_work(daily_fact):
                    display_status = "collecting" if _daily_fact_collecting(daily_fact) else "awaiting_evidence"
                elif _daily_fact_collecting_or_waiting(daily_fact):
                    display_status = "awaiting_evidence"
            if display_status == "coverage_insufficient":
                status_label = "覆盖不足"
            elif display_status == "target_fact_missing":
                status_label = "目标数据未产出"
            elif display_status == "build_failed":
                status_label = "构建失败"
            elif display_status == "awaiting_evidence" and not source_daily_available:
                status_label = "源数据暂不可读"
            elif display_status == "completed" and raw_failure_audit_only:
                status_label = "已完成，有采集审计"
            else:
                status_label = label_map.get(display_status, str(item.get("status_label") or "待提交抓取"))
            rows.append(
                {
                    "schedule_code": item.get("schedule_code"),
                    "schedule_group": item.get("schedule_group"),
                    "source_table_name": table,
                    "asset_label": _dashboard_table_label(table),
                    "scheduled_at": item.get("scheduled_at"),
                    "scheduled_at_local": item.get("scheduled_at_local"),
                    "run_slot": item.get("run_slot"),
                    "trading_day": item.get("trading_day"),
                    "priority": request_body.get("priority"),
                    "trigger_type": request_body.get("trigger_type"),
                    "universe_scope": request_body.get("universe_scope"),
                    "symbol_count": len(request_body.get("symbols") or []),
                    "status": display_status,
                    "task_status": item.get("task_status"),
                    "status_label": status_label,
                    "repairability": repairability,
                    "gap_summary": {"count": 0, "p0_count": 0, "p1_count": 0, "top_codes": []},
                    "fetch_batch_id": None,
                    "latest_build_status": None,
                    "latest_build_finished_at": daily_fact.get("latest_build_finished_at"),
                    "source_row_count": daily_fact.get("source_row_count"),
                    "lineage_row_count": daily_fact.get("lineage_row_count"),
                    "raw_failed_count": int(daily_fact.get("raw_failed_count") or 0),
                    "raw_cancelled_count": int(daily_fact.get("raw_cancelled_count") or 0),
                    "raw_waiting_count": int(daily_fact.get("raw_waiting_count") or 0),
                    "raw_active_count": int(daily_fact.get("raw_active_count") or 0),
                    "build_failed_count": int(daily_fact.get("build_failed_count") or 0),
                    "data_asset_status": daily_fact.get("data_asset_status"),
                    "final_data_failed": final_data_failed,
                    "raw_failure_audit_only": raw_failure_audit_only,
                    "scheduler_task_instance_id": item.get("task_instance_id"),
                    "scheduler_updated_at": item.get("updated_at"),
                    "scheduler_error_code": item.get("error_code"),
                    "source_fetch_batch_id": item.get("source_fetch_batch_id"),
                    "source_fetch_status": item.get("source_fetch_status"),
                    "source_submitted_job_count": source_submitted_job_count,
                    "source_skipped_duplicate_count": source_skipped_duplicate_count,
                    "source_producer_ack": item.get("source_producer_ack"),
                }
            )
        return sorted(rows, key=lambda row: str(row.get("scheduled_at_local") or row.get("scheduled_at") or ""))

    materialized = _payload_rows(payloads.get("source_schedule_materialized"), key="instances")
    now_dt = datetime.now(TBOARD_MARKET_TIMEZONE)
    now_key = _dashboard_time_key(now_dt.isoformat())
    rows = []
    for item in materialized:
        table = str(item.get("source_table_name") or "").strip()
        scheduled_key = _dashboard_time_key(item.get("scheduled_at_local") or item.get("scheduled_at"))
        request_body = item.get("request_body") if isinstance(item.get("request_body"), dict) else {}
        has_daily_fact = table in source_daily_tables
        daily_fact = source_daily_tables.get(table, {})
        status = "not_due" if scheduled_key > now_key else "awaiting_dispatch"
        final_data_failed = _daily_fact_final_data_failed(daily_fact)
        raw_failure_audit_only = _daily_fact_raw_audit_only(daily_fact)
        task_lifecycle_expired = _admin_task_lifecycle_expired(item, now=now_dt)
        if status != "not_due" and final_data_failed:
            status = "coverage_insufficient" if str(daily_fact.get("data_asset_status") or "").lower() == "coverage_insufficient" else ("build_failed" if int(daily_fact.get("build_failed_count") or 0) else "target_fact_missing")
        elif status != "not_due" and source_daily_available and task_lifecycle_expired and (not has_daily_fact or not _daily_fact_has_completion_evidence(daily_fact)):
            status = "expired_closed"
        elif status != "not_due" and _daily_fact_expired_closed(daily_fact):
            status = "expired_closed"
        elif status != "not_due" and has_daily_fact and _daily_fact_collecting_or_waiting(daily_fact):
            status = "collecting" if _daily_fact_collecting(daily_fact) else "awaiting_evidence"
        status_label = "未到抓取时间" if status == "not_due" else "待提交抓取"
        if status == "coverage_insufficient":
            status_label = "覆盖不足"
        elif status == "target_fact_missing":
            status_label = "目标数据未产出"
        elif status == "build_failed":
            status_label = "构建失败"
        elif status == "awaiting_evidence":
            status_label = "??????"
        elif status == "expired_closed":
            status_label = "?????"
        elif status == "collecting":
            status_label = "????/??"
        rows.append(
            {
                "schedule_code": item.get("schedule_code"),
                "schedule_group": item.get("schedule_group"),
                "source_table_name": table,
                "asset_label": _dashboard_table_label(table),
                "scheduled_at": item.get("scheduled_at"),
                "scheduled_at_local": item.get("scheduled_at_local"),
                "run_slot": item.get("run_slot"),
                "trading_day": item.get("trading_day"),
                "priority": request_body.get("priority"),
                "trigger_type": request_body.get("trigger_type"),
                "universe_scope": request_body.get("universe_scope"),
                "symbol_count": len(request_body.get("symbols") or []),
                "status": status,
                "status_label": status_label,
                "repairability": {"code": "contract_pending", "label": "补全能力待确认", "reason": "未读取到 scheduler 任务账本汇总。"},
                "gap_summary": {"count": 0, "p0_count": 0, "p1_count": 0, "top_codes": []},
                "fetch_batch_id": None,
                "latest_build_status": None,
                "latest_build_finished_at": None,
                "source_row_count": None,
                "lineage_row_count": None,
                "raw_waiting_count": int(daily_fact.get("raw_waiting_count") or 0),
                "raw_active_count": int(daily_fact.get("raw_active_count") or 0),
                "data_asset_status": daily_fact.get("data_asset_status"),
                "final_data_failed": final_data_failed,
                "raw_failure_audit_only": raw_failure_audit_only,
            }
        )
    return sorted(rows, key=lambda row: str(row.get("scheduled_at_local") or row.get("scheduled_at") or ""))


def _admin_task_summary(task_rows: list[dict[str, Any]], payloads: dict[str, Any]) -> dict[str, Any]:
    queue = _queue_summary(payloads.get("queue_summary"))
    scheduler_daily = _payload_dict(payloads.get("scheduler_daily_summary"))
    scheduler_summary = scheduler_daily.get("summary") if isinstance(scheduler_daily.get("summary"), dict) else {}
    source_daily_payload = payloads.get("source_daily_summary")
    source_facts_available = _payload_available(source_daily_payload)
    source_daily = _payload_dict(source_daily_payload)
    source_summary = source_daily.get("summary") if isinstance(source_daily.get("summary"), dict) else {}
    scheduler_status_counts = (
        scheduler_summary.get("status_counts")
        if isinstance(scheduler_summary.get("status_counts"), dict)
        else {}
    )
    scheduler_completed_tasks = int(scheduler_summary.get("completed_task_count") or 0)
    scheduler_due_tasks = int(scheduler_summary.get("due_task_count") or 0)
    scheduler_unfinished_tasks = int(scheduler_summary.get("unfinished_task_count") or 0)
    scheduler_not_due_tasks = int(scheduler_summary.get("not_due_task_count") or 0)
    failed_statuses = {"failed", "target_fact_missing", "build_failed", "coverage_insufficient", "data_failed"}
    data_failed_statuses = {"target_fact_missing", "build_failed", "coverage_insufficient", "data_failed"}
    expired_closed_statuses = {"expired_closed"}
    if task_rows:
        total_tasks = int(scheduler_summary.get("planned_task_count") or len(task_rows))
        completed_tasks = sum(1 for row in task_rows if row.get("status") in {"completed", "build_succeeded_target_check"})
        waiting_collection_tasks = sum(1 for row in task_rows if row.get("status") == "not_due")
        collecting_tasks = sum(1 for row in task_rows if row.get("status") in {"collecting", "queue_active"})
        execution_failed_tasks = sum(1 for row in task_rows if row.get("status") == "failed")
        awaiting_dispatch_tasks = sum(1 for row in task_rows if row.get("status") == "awaiting_dispatch")
        awaiting_evidence_tasks = sum(1 for row in task_rows if row.get("status") == "awaiting_evidence")
        expired_closed_tasks = sum(1 for row in task_rows if row.get("status") in expired_closed_statuses)
    elif scheduler_summary:
        total_tasks = int(scheduler_summary.get("planned_task_count") or len(task_rows))
        completed_tasks = int(scheduler_summary.get("completed_task_count") or 0)
        waiting_collection_tasks = int(scheduler_summary.get("not_due_task_count") or 0)
        collecting_tasks = int(scheduler_summary.get("collecting_task_count") or 0)
        execution_failed_tasks = int(scheduler_summary.get("failed_task_count") or 0)
        awaiting_dispatch_tasks = int(scheduler_summary.get("awaiting_dispatch_task_count") or 0)
        awaiting_evidence_tasks = 0
        expired_closed_tasks = int(source_summary.get("expired_closed_table_count") or 0) if source_facts_available else 0
    else:
        total_tasks = len(task_rows)
        completed_tasks = sum(1 for row in task_rows if row["status"] == "completed")
        waiting_collection_tasks = sum(1 for row in task_rows if row["status"] == "not_due")
        collecting_tasks = sum(1 for row in task_rows if row["status"] == "collecting")
        execution_failed_tasks = sum(1 for row in task_rows if row["status"] == "failed")
        awaiting_dispatch_tasks = sum(1 for row in task_rows if row["status"] == "awaiting_dispatch")
        awaiting_evidence_tasks = sum(1 for row in task_rows if row["status"] == "awaiting_evidence")
        expired_closed_tasks = sum(1 for row in task_rows if row.get("status") in expired_closed_statuses)
    data_failed_rows = [row for row in task_rows if row.get("status") in data_failed_statuses]
    target_fact_missing_tasks = sum(1 for row in task_rows if row.get("status") == "target_fact_missing") if task_rows else int(source_summary.get("data_failed_table_count") or 0)
    build_failed_tasks = sum(1 for row in task_rows if row.get("status") == "build_failed") if task_rows else 0
    coverage_insufficient_tasks = sum(1 for row in task_rows if row.get("status") == "coverage_insufficient") if task_rows else int(source_summary.get("coverage_insufficient_table_count") or 0)
    data_failed_jobs = len(data_failed_rows) if task_rows else int(source_summary.get("data_failed_table_count") or 0)
    failed_tasks = sum(1 for row in task_rows if row.get("status") in failed_statuses) if task_rows else execution_failed_tasks + data_failed_jobs
    failed_rows = [row for row in task_rows if row.get("status") == "failed"]
    repairable_failed_tasks = sum(1 for row in failed_rows + data_failed_rows if row.get("repairability", {}).get("code") == "repairable_after_expiry")
    unrepairable_failed_tasks = sum(1 for row in failed_rows + data_failed_rows if row.get("repairability", {}).get("code") == "non_repairable_after_window")
    contract_pending_failed_tasks = max(failed_tasks - repairable_failed_tasks - unrepairable_failed_tasks, 0)
    unfinished_tasks = max(total_tasks - completed_tasks, 0)
    raw_waiting_jobs_total = int(source_summary.get("raw_waiting_jobs") or 0) if source_facts_available else None
    raw_active_jobs_total = int(source_summary.get("raw_active_jobs") or 0) if source_facts_available else None
    effective_raw_waiting_jobs: int | None = None
    effective_raw_active_jobs: int | None = None
    if source_facts_available:
        active_rows_by_table: dict[str, dict[str, Any]] = {}
        for row in task_rows:
            if row.get("status") not in {"collecting", "awaiting_evidence", "awaiting_dispatch", "queue_active"}:
                continue
            table = str(row.get("source_table_name") or "").strip()
            if table and table not in active_rows_by_table:
                active_rows_by_table[table] = row
        effective_raw_waiting_jobs = sum(int(row.get("raw_waiting_count") or 0) for row in active_rows_by_table.values())
        effective_raw_active_jobs = sum(int(row.get("raw_active_count") or 0) for row in active_rows_by_table.values())
    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "unfinished_tasks": unfinished_tasks,
        "scheduler_completed_tasks": scheduler_completed_tasks,
        "scheduler_due_tasks": scheduler_due_tasks,
        "scheduler_unfinished_tasks": scheduler_unfinished_tasks,
        "scheduler_not_due_tasks": scheduler_not_due_tasks,
        "scheduler_status_counts": scheduler_status_counts,
        "waiting_collection_tasks": waiting_collection_tasks,
        "collecting_tasks": collecting_tasks,
        "pending_acceptance_tasks": 0,
        "failed_tasks": failed_tasks,
        "execution_failed_tasks": execution_failed_tasks,
        "data_failed_jobs": data_failed_jobs,
        "source_facts_available": source_facts_available,
        "source_facts_status_label": "源数据已读取" if source_facts_available else "源数据暂不可读",
        "data_failed_assets": int(source_summary.get("data_failed_table_count") or 0) if source_facts_available else None,
        "raw_audit_warning_table_count": int(source_summary.get("audit_warning_table_count") or 0) if source_facts_available else None,
        "repairable_failed_tasks": repairable_failed_tasks,
        "unrepairable_failed_tasks": unrepairable_failed_tasks,
        "contract_pending_failed_tasks": contract_pending_failed_tasks,
        "not_due_tasks": waiting_collection_tasks,
        "target_fact_missing_tasks": target_fact_missing_tasks,
        "build_failed_tasks": build_failed_tasks,
        "coverage_insufficient_tasks": coverage_insufficient_tasks,
        "build_failed_result_count": int(source_summary.get("build_failed_results") or 0) if source_facts_available else None,
        "built_tasks": completed_tasks,
        "awaiting_dispatch_tasks": awaiting_dispatch_tasks,
        "awaiting_evidence_tasks": awaiting_evidence_tasks,
        "expired_closed_tasks": expired_closed_tasks,
        "inspection_unknown_tasks": 0,
        "queue_active_tasks": collecting_tasks,
        "raw_failed_jobs": int(source_summary.get("raw_failed_jobs") or 0) if source_facts_available else None,
        "raw_cancelled_jobs": int(source_summary.get("raw_cancelled_jobs") or 0) if source_facts_available else None,
        "raw_waiting_jobs": effective_raw_waiting_jobs,
        "raw_active_jobs": effective_raw_active_jobs,
        "raw_waiting_jobs_total": raw_waiting_jobs_total,
        "raw_active_jobs_total": raw_active_jobs_total,
        "raw_succeeded_jobs": int(source_summary.get("raw_succeeded_jobs") or 0) if source_facts_available else None,
        "build_result_count": int(source_summary.get("build_result_count") or 0) if source_facts_available else None,
        "source_row_count": int(source_summary.get("source_row_count") or 0) if source_facts_available else None,
        "latest_data_update_at": source_summary.get("latest_data_update_at") if source_facts_available else None,
        "latest_task_update_at": scheduler_summary.get("latest_task_update_at"),
        "queue": queue,
    }

async def _fetch_admin_task_board_payloads(request: Request, trade_date: date) -> dict[str, Any]:
    headers = _read_only_headers(request)
    scheduler_daily_summary_path = f"scheduler/task-store/daily-summary?trading_day={trade_date.isoformat()}&owner_service=source-data-service"
    source_daily_summary_path = f"source/ops/daily-data-summary?trade_date={trade_date.isoformat()}"
    requests = {
        "requirements": ("source", "source/requirements"),
        "freshness_sla": ("source", "source/freshness/sla"),
        "repair_routes": ("source", "source/repair-routes"),
        "queue_summary": ("source", "source/fetch/queues/summary"),
        "source_daily_summary": ("source", source_daily_summary_path),
        "scheduler_daily_summary": ("scheduler", scheduler_daily_summary_path),
    }
    async with httpx.AsyncClient(timeout=_admin_dashboard_timeout_seconds(), follow_redirects=False) as client:
        names = list(requests)
        tasks = [
            _fetch_backend_json(client, service=service, path=path, headers=headers)
            for service, path in requests.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return dict(zip(names, results, strict=True))


async def _fetch_admin_dashboard_payloads(request: Request, trade_date: date) -> dict[str, Any]:
    headers = _read_only_headers(request)
    source_materialized_path = f"scheduler/materialize/source-schedule?trading_day={trade_date.isoformat()}"
    scheduler_daily_summary_path = f"scheduler/task-store/daily-summary?trading_day={trade_date.isoformat()}&owner_service=source-data-service"
    source_daily_summary_path = f"source/ops/daily-data-summary?trade_date={trade_date.isoformat()}"
    latest_inspection_path = f"inspection-runs/latest?scope=core_closure&as_of_trading_day={trade_date.isoformat()}"
    requests = {
        "requirements": ("source", "source/requirements"),
        "freshness_sla": ("source", "source/freshness/sla"),
        "readiness_matrix": ("source", "source/readiness/matrix"),
        "repair_routes": ("source", "source/repair-routes"),
        "queue_summary": ("source", "source/fetch/queues/summary"),
        "source_daily_summary": ("source", source_daily_summary_path),
        "build_results": ("source", "source/build/results"),
        "build_triggers": ("source", "source/build/triggers"),
        "storage_policies": ("source", "source/storage/policies"),
        "source_schedule_registry": ("scheduler", "scheduler/source-schedule/registry"),
        "source_schedule_materialized": ("scheduler", source_materialized_path),
        "scheduler_daily_summary": ("scheduler", scheduler_daily_summary_path),
        "scheduler_runtime": ("scheduler", "scheduler/runtime/status"),
        "inspection_latest": ("data-inspector", latest_inspection_path),
    }
    async with httpx.AsyncClient(timeout=_admin_dashboard_timeout_seconds(), follow_redirects=False) as client:
        names = list(requests)
        tasks = [
            _fetch_backend_json(client, service=service, path=path, headers=headers)
            for service, path in requests.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    payloads = dict(zip(names, results, strict=True))
    latest = _payload_dict(payloads.get("inspection_latest"))
    run_id = latest.get("run_id")
    if run_id is not None:
        async with httpx.AsyncClient(timeout=_admin_dashboard_timeout_seconds(), follow_redirects=False) as client:
            payloads["inspection_gaps"] = await asyncio.gather(
                _fetch_backend_json(
                    client,
                    service="data-inspector",
                    path=f"inspection-gaps?run_id={run_id}&limit={ADMIN_DASHBOARD_LIMIT}",
                    headers=headers,
                ),
                return_exceptions=True,
            )
            payloads["inspection_gaps"] = payloads["inspection_gaps"][0]
    else:
        payloads["inspection_gaps"] = []
    return payloads
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
            "admin-ops",
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
    user = _authenticate_user(username, password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = secrets.token_urlsafe(32)
    SESSION_STORE[token] = user
    response = JSONResponse({"authenticated": True, "user": user})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return response


@app.get("/api/auth/session")
def session(request: Request) -> dict[str, Any]:
    user = _session_user(request)
    return {"authenticated": user is not None, "user": user}


@app.post("/api/auth/logout")
def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        SESSION_STORE.pop(token, None)
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


@app.get("/api/admin/daily-board")
async def admin_daily_board(request: Request, trade_date: str | None = None) -> dict[str, Any]:
    user = _require_admin(request)
    day = _dashboard_trade_date(trade_date)
    payloads = await _cached_admin_payloads("daily-board", day, lambda: _fetch_admin_dashboard_payloads(request, day))
    inspection_coverage = _admin_inspection_coverage(payloads, day)
    asset_rows = _admin_asset_rows(payloads, day, inspection_coverage)
    return {
        "contract_kind": "shence_admin_daily_data_board_v1",
        "read_only": True,
        "role_required": "admin",
        "viewer": user,
        "trade_date": day.isoformat(),
        "generated_at": datetime.now(TBOARD_MARKET_TIMEZONE).isoformat(),
        "refresh_interval_seconds": ADMIN_DASHBOARD_REFRESH_SECONDS,
        "summary": _admin_data_summary(asset_rows, payloads, inspection_coverage),
        "assets": asset_rows,
        "gaps": _payload_rows(payloads.get("inspection_gaps"))[:ADMIN_DASHBOARD_LIMIT],
        "upstream_status": _admin_upstream_status(payloads),
        "guardrails": {
            "mutates_source_facts": False,
            "mutates_scheduler_facts": False,
            "mutates_model_facts": False,
            "direct_provider_calls_allowed": False,
            "target_fact_completion_is_separate_from_task_success": True,
        },
    }


@app.get("/api/admin/task-board")
async def admin_task_board(request: Request, trade_date: str | None = None) -> dict[str, Any]:
    user = _require_admin(request)
    day = _dashboard_trade_date(trade_date)
    payloads = await _cached_admin_payloads("task-board", day, lambda: _fetch_admin_task_board_payloads(request, day))
    task_rows = _admin_task_rows(payloads)
    return {
        "contract_kind": "shence_admin_daily_task_board_v1",
        "read_only": True,
        "role_required": "admin",
        "viewer": user,
        "trade_date": day.isoformat(),
        "generated_at": datetime.now(TBOARD_MARKET_TIMEZONE).isoformat(),
        "refresh_interval_seconds": ADMIN_DASHBOARD_REFRESH_SECONDS,
        "summary": _admin_task_summary(task_rows, payloads),
        "tasks": task_rows,
        "upstream_status": _admin_upstream_status(payloads),
        "guardrails": {
            "mutates_source_facts": False,
            "mutates_scheduler_facts": False,
            "direct_provider_calls_allowed": False,
            "task_success_does_not_imply_target_fact_completion": True,
        },
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
