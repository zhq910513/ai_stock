from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from t_board_relay_model_service.config import MODEL_VERSION, SERVICE_NAME, get_settings
from t_board_relay_model_service.logic import (
    response_for_day1_scan,
    response_for_day2_trigger,
    response_for_day2_watch,
    response_for_day3_exit,
    response_for_outcome,
    response_for_post_entry_monitor,
)
from t_board_relay_model_service.repository import TBoardRelayRepository
from t_board_relay_model_service.schemas import ModelServiceResponse, TBoardRelayRequest


router = APIRouter(tags=["t-board-relay-model"])
prefixed_router = APIRouter(prefix="/t-board-relay", tags=["t-board-relay-model"])


def _payload(request: TBoardRelayRequest) -> dict[str, Any]:
    merged = dict(request.payload or {})
    if request.row:
        merged.update(request.row)
    if request.trade_date and "trade_date" not in merged:
        merged["trade_date"] = request.trade_date.isoformat()
    if request.as_of_time_utc and "as_of_time_utc" not in merged:
        merged["as_of_time_utc"] = request.as_of_time_utc.isoformat()
    if request.run_id and "run_id" not in merged:
        merged["run_id"] = request.run_id
    return merged


def _rows(request: TBoardRelayRequest) -> list[dict[str, Any]]:
    if request.rows:
        return request.rows
    if isinstance(request.payload.get("rows"), list):
        return request.payload["rows"]
    if request.row:
        return [request.row]
    if request.payload:
        return [request.payload]
    return []


def _repository() -> TBoardRelayRepository:
    settings = get_settings()
    return TBoardRelayRepository(settings.effective_database_url, persist_decisions=settings.persist_decisions)


def _request_payload(request: TBoardRelayRequest) -> dict[str, Any]:
    return request.model_dump(mode="json")


def _run_id(request: TBoardRelayRequest, payload: dict[str, Any]) -> str | None:
    return request.run_id or payload.get("run_id")


def _with_repository_write(
    *,
    stage: str,
    request: TBoardRelayRequest,
    payload: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    write_result = _repository().persist_response(
        stage=stage,
        request_payload=_request_payload(request),
        response_body=body,
        run_id=_run_id(request, payload),
    )
    body.setdefault("structured_output", {})["repository_write"] = write_result
    return body


def _empty_repository_response(entity: str) -> dict[str, Any]:
    status = _repository().status()
    return {
        "contract_kind": f"t_board_relay_{entity}_repository_view_v1",
        "repository_attached": status.get("repository_attached") is True,
        "items": [],
        "warning_codes": status.get("warning_codes") or ["repository_not_attached"],
        "repository_status": status,
    }


def _repository_list_response(entity: str, *, limit: int) -> dict[str, Any]:
    repo = _repository()
    status = repo.status()
    if status.get("repository_attached") is not True:
        return _empty_repository_response(entity)
    rows = repo.list_rows(entity, limit=limit)
    return {
        "contract_kind": f"t_board_relay_{entity}_repository_view_v1",
        "repository_attached": True,
        "items": rows,
        "warning_codes": [],
        "repository_status": status,
    }


SOURCE_GAP_LABELS = {
    "source_gap:seal_order_snapshot_missing": "封单快照待补",
    "source_gap:dynamic_feature_bundle_missing": "盘中特征待补",
    "source_gap:near_limit_order_absorption_missing": "盘口吸收待补",
    "source_gap:minute_bar_or_realtime_quote_missing": "分钟行情待补",
    "source_gap:order_book_snapshot_missing": "盘口快照待补",
    "source_gap:trade_tick_missing": "逐笔成交待补",
    "source_gap:post_entry_board_monitor_missing": "封板维护待补",
    "source_gap:day3_open_price_missing": "第三日开盘待补",
    "source_gap:day3_tail_price_missing": "第三日尾盘待补",
}


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value in (None, ""):
        return None
    else:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _positive_int(value: Any, default: int, *, upper: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        parsed = default
    if upper is not None:
        parsed = min(parsed, upper)
    return parsed


def _record_order_value(item: dict[str, Any]) -> tuple[str, int]:
    for field in ("updated_at", "created_at", "available_at", "captured_at", "latest_snapshot_time", "as_of_time", "as_of_time_utc"):
        value = item.get(field)
        if value:
            return (str(value), 0)
    for field in ("day1_candidate_pk", "day2_watch_pk", "entry_trigger_pk", "post_entry_monitor_pk", "day3_decision_pk", "outcome_label_pk", "game_hypothesis_pk"):
        try:
            return ("", int(item.get(field) or 0))
        except (TypeError, ValueError):
            continue
    return ("", 0)


def _keep_latest(mapping: dict[str, dict[str, Any]], key: str | None, item: dict[str, Any]) -> None:
    if not key:
        return
    current = mapping.get(key)
    if current is None or _record_order_value(item) >= _record_order_value(current):
        mapping[key] = item


def _display_time(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0).isoformat()
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[1].split("+", 1)[0].split("Z", 1)[0].split(".", 1)[0]
    if " " in text:
        return text.rsplit(" ", 1)[-1].split("+", 1)[0].split(".", 1)[0]
    return text


DEFAULT_MONITOR_INTERVAL_MINUTES = 5
MODEL_RESULT_INTERVAL_MINUTES = 30
OBSERVATION_SORT_WINDOW_LIMIT = 500
OBSERVATION_SCORE_VERSION = "t_board_relay_observation_score_v1"
MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
DAY2_WATCH_WINDOW_END = time(10, 30)


def _latest_record_time(*items: dict[str, Any]) -> Any:
    for item in items:
        if not item:
            continue
        for field in ("updated_at", "created_at", "available_at", "captured_at", "as_of_time", "as_of_time_utc"):
            value = item.get(field)
            if value:
                return value
    return None


def _latest_time_value(*items: dict[str, Any]) -> Any:
    best_dt: datetime | None = None
    best_value: Any = None
    for item in items:
        if not item:
            continue
        item_value: Any = None
        item_dt: datetime | None = None
        for field in ("as_of_time", "captured_at", "available_at", "as_of_time_utc", "updated_at", "created_at"):
            value = item.get(field)
            parsed = _parse_iso_datetime(value)
            if parsed:
                item_value = value
                item_dt = parsed
                break
        if item_dt and (best_dt is None or item_dt >= best_dt):
            best_dt = item_dt
            best_value = item_value
    return best_value


def _projection_generated_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _time_seconds(value: Any) -> int | None:
    text = _display_time(value)
    if not text:
        return None
    parts = str(text).split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return hour * 3600 + minute * 60 + second


def _day2_watch_window_complete(day2_watch: dict[str, Any]) -> bool:
    seconds = _time_seconds(day2_watch.get("as_of_time") or day2_watch.get("monitor_check_time"))
    return seconds is not None and seconds >= DAY2_WATCH_WINDOW_END.hour * 3600 + DAY2_WATCH_WINDOW_END.minute * 60


def _next_weekday(day_value: date) -> date:
    next_day = day_value + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day


def _day2_window_elapsed(day1_trade_date: Any) -> bool:
    day1 = _parse_iso_date(day1_trade_date)
    if day1 is None:
        return False
    now = datetime.now(MARKET_TIMEZONE)
    if now.date().weekday() >= 5:
        return False
    day2 = _next_weekday(day1)
    if now.date() > day2:
        return True
    if now.date() < day2:
        return False
    return now.time() >= DAY2_WATCH_WINDOW_END


def _last_monitor_time(
    *,
    day2_watch: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    post_entry: dict[str, Any] | None,
    day3: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
) -> Any:
    ordered = (
        (outcome or {}, ("updated_at", "created_at", "available_at")),
        (day3 or {}, ("updated_at", "created_at", "available_at")),
        (post_entry or {}, ("updated_at", "created_at", "available_at")),
        (trigger or {}, ("trigger_time", "updated_at", "created_at", "available_at")),
        (day2_watch or {}, ("as_of_time", "updated_at", "created_at", "available_at")),
    )
    for item, fields in ordered:
        for field in fields:
            value = item.get(field)
            if value:
                return value
    return None


def _monitoring_summary(
    *,
    status: str,
    valid_day2_watch: dict[str, Any] | None,
    valid_trigger: dict[str, Any] | None,
    post_entry: dict[str, Any] | None,
    day3: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
    last_monitor_at: Any,
) -> str:
    monitor_time = _display_time(last_monitor_at)
    suffix = f"\uff0c\u6700\u8fd1\u66f4\u65b0 {monitor_time}" if monitor_time else ""
    if outcome:
        return "\u7ed3\u679c\u5df2\u843d\u5b9e\uff0c\u8fdb\u5165\u590d\u76d8"
    if day3:
        return f"Day3 \u53bb\u7559\u5df2\u66f4\u65b0{suffix}"
    if post_entry:
        return f"Day2 \u89e6\u53d1\u540e\u5c01\u677f\u7ef4\u62a4\u5df2\u66f4\u65b0{suffix}"
    if valid_trigger:
        trigger_time = _display_time(valid_trigger.get("trigger_time"))
        trigger_status = valid_trigger.get("entry_trigger_status")
        not_trigger_reason = valid_trigger.get("not_trigger_reason")
        if status == "opportunity":
            prefix = f"Day2 {trigger_time} \u89e6\u53d1\u540e" if trigger_time else "Day2 \u89e6\u53d1\u540e"
            return f"{prefix}\uff0c\u6309\u6bcf5\u5206\u949f\u8ddf\u8e2a\u5c01\u677f"
        if trigger_status == "not_triggered" and not_trigger_reason == "day2_not_near_limit_rolling_5m":
            return "Day2 09:30-10:30 \u6bcf5\u5206\u949f\u76d1\u6d4b\u5df2\u7ed3\u675f\uff0c\u672a\u63a5\u8fd1\u6da8\u505c"
        if trigger_status == "data_blocked":
            return "Day2 \u6bcf5\u5206\u949f\u76d1\u6d4b\u4e2d\u51fa\u73b0\u4e8b\u5b9e\u7f3a\u53e3\uff0c\u7b49\u5f85\u8865\u9f50\u540e\u590d\u6838"
        prefix = f"Day2 {trigger_time} \u76d8\u53e3\u786e\u8ba4" if trigger_time else "Day2 \u76d8\u53e3\u786e\u8ba4"
        return f"{prefix}\uff0c\u5f53\u524d\u7ed3\u8bba\u5df2\u66f4\u65b0"
    if valid_day2_watch:
        watch_time = _display_time((valid_day2_watch or {}).get("as_of_time")) or monitor_time
        suffix = f"\uff0c\u6700\u8fd1\u68c0\u67e5 {watch_time}" if watch_time else ""
        return f"Day2 \u6bcf5\u5206\u949f\u6eda\u52a8\u76d1\u6d4b{suffix}"
    return "Day2 \u5f00\u76d8\u540e\u6bcf5\u5206\u949f\u5f00\u59cb\u89c2\u5bdf"


def _gap_labels(*items: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in items:
        for code in item.get("source_gap_codes") or []:
            label = SOURCE_GAP_LABELS.get(str(code), "待补事实")
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return labels


def _relay_strength_label(score: Any) -> str:
    if score in (None, ""):
        return "等待触发数据"
    try:
        value = Decimal(str(score))
    except Exception:
        return "等待触发数据"
    if value >= Decimal("80"):
        return "强"
    if value >= Decimal("60"):
        return "中"
    if value > Decimal("0"):
        return "弱"
    return "等待触发数据"


def _is_qualified_day1(item: dict[str, Any]) -> bool:
    return (
        item.get("candidate_status") == "qualified"
        and item.get("is_t_board") is True
        and item.get("float_market_cap_pass") is True
    )


def _is_later_trading_stage(day1_trade_date: Any, stage_trade_date: Any) -> bool:
    day1 = _parse_iso_date(day1_trade_date)
    stage_date = _parse_iso_date(stage_trade_date)
    return bool(day1 and stage_date and stage_date > day1)


def _positive_decimal(value: Any) -> bool:
    try:
        return Decimal(str(value)) > 0
    except Exception:
        return False


def _trigger_has_ask_sweep(trigger: dict[str, Any]) -> bool:
    return str(trigger.get("order_consumption_side") or "").upper() == "ASK" and _positive_decimal(trigger.get("order_consumption_amount"))


def _trigger_has_bid_pressure(trigger: dict[str, Any]) -> bool:
    return str(trigger.get("order_consumption_side") or "").upper() == "BID" and _positive_decimal(trigger.get("order_consumption_amount"))


def _build_observation_item(
    *,
    day1: dict[str, Any],
    day2_watch: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    post_entry: dict[str, Any] | None,
    day3: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
    hypothesis: dict[str, Any] | None,
) -> dict[str, Any]:
    stage = "首日已入选"
    status = "continue_watch"
    conclusion = "等待下一交易日开盘后滚动观察"
    next_observation = "下一交易日09:30后每5分钟观察"
    key_reason = "首日通过T字板和流通市值规则"
    risk_tip = "Day2盘口尚未验证，风险待开盘滚动监测确认"
    data_notice = "事实已齐"
    valid_trigger = trigger if trigger and _is_later_trading_stage(day1.get("trade_date"), trigger.get("day2_trade_date")) else None
    ignored_stage_reasons: list[str] = []
    if trigger and not valid_trigger:
        ignored_stage_reasons.append("次日交易日待校验")
    post_entry = post_entry if valid_trigger and post_entry else None
    raw_day3 = day3
    day3 = raw_day3 if valid_trigger and raw_day3 and _is_later_trading_stage(valid_trigger.get("day2_trade_date"), raw_day3.get("day3_trade_date")) else None
    if valid_trigger and day3 is None and (raw_day3 or {}).get("day3_trade_date"):
        ignored_stage_reasons.append("第三日交易日待校验")
    outcome = outcome if valid_trigger and outcome else None
    hypothesis = hypothesis if valid_trigger and hypothesis else None

    if valid_trigger:
        trigger_status = valid_trigger.get("entry_trigger_status")
        stage = "Day2 观察"
        if trigger_status == "triggered" and _trigger_has_bid_pressure(valid_trigger):
            status = "stopped"
            conclusion = "卖盘主动砸向买盘，停止观察"
            next_observation = "无需继续跟踪"
            key_reason = "Day2 接近涨停时卖盘主动砸向买盘"
            risk_tip = "接近涨停时卖盘主动砸向买盘，承接转弱，追高风险高"
        elif trigger_status == "triggered" and not _trigger_has_ask_sweep(valid_trigger):
            status = "data_wait"
            conclusion = "盘口方向待确认，暂不提示买入"
            next_observation = "补齐逐笔方向和成交力度后复核"
            key_reason = "Day2 接近涨停，但买盘扫卖盘尚未确认"
            risk_tip = "缺逐笔方向或成交强度，无法确认买盘扫卖盘"
            data_notice = "盘口确认待补"
        elif trigger_status == "triggered":
            status = "opportunity"
            conclusion = "接力机会已触发，可买入观察"
            next_observation = "观察触发后是否封住到收盘"
            key_reason = "Day2 接近涨停，买盘主动扫掉卖盘"
            risk_tip = "买盘扫卖盘已确认，主要风险转为触发后能否封住到收盘"
        elif trigger_status == "data_blocked":
            status = "data_wait"
            conclusion = "数据不足，先不判断"
            next_observation = "补齐 Day2 分钟行情后复核"
            key_reason = "Day2 滚动监测关键行情未齐"
            risk_tip = "分钟行情或盘口关键事实缺失，暂无法评估接力风险"
            data_notice = "分钟行情待补"
        else:
            status = "stopped"
            conclusion = "Day2 未到接力点，停止观察"
            next_observation = "无需继续跟踪"
            key_reason = "Day2 09:30-10:30 滚动监测未接近涨停"
            risk_tip = "09:30-10:30 未接近涨停，日内强度未达到接力阈值"

    if post_entry:
        post_status = post_entry.get("post_entry_status")
        stage = "封板维护"
        if post_status == "FAILED_AFTER_OPEN" or post_entry.get("outcome_label") == "day2_board_open_after_entry_failed":
            status = "stopped"
            conclusion = "触发后开板，停止观察"
            next_observation = "无需继续跟踪"
            key_reason = "理论触发后出现开板"
            risk_tip = "触发后开板，封板维护失败，Day3退出风险升高"
        elif post_status:
            status = "continue_watch"
            conclusion = "封住到收盘，Day3 继续观察"
            next_observation = "Day3 开盘和尾盘观察"
            key_reason = "触发后未见开板失败"
            risk_tip = "触发后未见开板，风险转为Day3开盘能否继续涨停"

    if day3:
        action = day3.get("day3_action")
        stage = "Day3 去留"
        if action == "hold_open_limit":
            status = "continue_watch"
            conclusion = "Day3 强势，继续留意"
            next_observation = "继续观察 Day3 封板质量"
            key_reason = "Day3 开盘涨停"
            risk_tip = "Day3开盘涨停，继续观察封单质量和尾盘强度"
        elif action == "exit_tail_no_limit":
            status = "stopped"
            conclusion = "Day3 转弱，停止观察"
            next_observation = "无需继续跟踪"
            key_reason = "Day3 尾盘未涨停"
            risk_tip = "Day3尾盘未涨停，短线强度转弱"
        elif action:
            conclusion = "Day3 等待确认"
            next_observation = "等待 Day3 尾盘观察"

    if outcome:
        label = outcome.get("outcome_label")
        if label in {"relay_success", "t_board_relay_strong_success"}:
            status = "completed"
            conclusion = "接力兑现"
            next_observation = "进入复盘"
            key_reason = "结果标签已完成"
            risk_tip = "结果已兑现，进入复盘，不再追踪日内风险"
        elif label in {"relay_failed", "day2_board_open_after_entry_failed"}:
            status = "stopped"
            conclusion = "接力失败，停止观察"
            next_observation = "进入复盘"
            key_reason = "结果标签已完成"
            risk_tip = "结果已失败，进入复盘，只保留样本归因"

    labels = _gap_labels(day1, valid_trigger or {}, post_entry or {}, day3 or {}, outcome or {})
    if labels and status not in {"stopped", "completed"}:
        data_notice = "部分事实待补"
    if ignored_stage_reasons:
        data_notice = "；".join(ignored_stage_reasons)

    latest_snapshot_time = None
    for item in (outcome or {}, day3 or {}, post_entry or {}, valid_trigger or {}, day1):
        if not item:
            continue
        latest_snapshot_time = item.get("updated_at") or item.get("created_at") or item.get("available_at")
        if latest_snapshot_time:
            break
    return {
        "observation_id": day1.get("day1_candidate_id"),
        "stock": {"symbol": day1.get("canonical_symbol"), "name": day1.get("stock_name")},
        "day1_trade_date": day1.get("trade_date"),
        "day2_trade_date": valid_trigger.get("day2_trade_date") if valid_trigger else None,
        "day2_trigger_time": valid_trigger.get("trigger_time") if valid_trigger else None,
        "day3_trade_date": day3.get("day3_trade_date") if day3 else None,
        "observation_status": status,
        "current_stage": stage,
        "current_conclusion": conclusion,
        "next_observation": next_observation,
        "key_reason": key_reason,
        "relay_strength_label": _relay_strength_label(valid_trigger.get("relay_consensus_score") if valid_trigger else None),
        "risk_tip": risk_tip,
        "data_notice": data_notice,
        "data_gap_count": len(labels),
        "data_gap_labels": labels,
        "latest_snapshot_time": latest_snapshot_time,
        "game_state_label": (hypothesis or {}).get("game_state_label"),
    }


# Canonical user-facing observation labels. Keep these as unicode escapes so the
# source remains stable across Windows terminals with different code pages.
SOURCE_GAP_LABELS = {
    "source_gap:seal_order_snapshot_missing": "\u5c01\u5355\u5feb\u7167\u5f85\u8865",
    "source_gap:dynamic_feature_bundle_missing": "\u76d8\u4e2d\u7279\u5f81\u5f85\u8865",
    "source_gap:near_limit_order_absorption_missing": "\u76d8\u53e3\u5438\u6536\u5f85\u8865",
    "source_gap:minute_bar_or_realtime_quote_missing": "\u5206\u949f\u884c\u60c5\u5f85\u8865",
    "source_gap:order_book_snapshot_missing": "\u76d8\u53e3\u5feb\u7167\u5f85\u8865",
    "source_gap:trade_tick_missing": "\u9010\u7b14\u6210\u4ea4\u5f85\u8865",
    "source_gap:post_entry_board_monitor_missing": "\u5c01\u677f\u7ef4\u62a4\u5f85\u8865",
    "source_gap:day3_open_price_missing": "\u7b2c\u4e09\u65e5\u5f00\u76d8\u5f85\u8865",
    "source_gap:day3_tail_price_missing": "\u7b2c\u4e09\u65e5\u5c3e\u76d8\u5f85\u8865",
}


def _gap_labels(*items: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in items:
        for code in item.get("source_gap_codes") or []:
            label = SOURCE_GAP_LABELS.get(str(code), "\u5f85\u8865\u4e8b\u5b9e")
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return labels


def _relay_strength_label(score: Any) -> str:
    if score in (None, ""):
        return "\u7b49\u5f85\u89e6\u53d1\u6570\u636e"
    try:
        value = Decimal(str(score))
    except Exception:
        return "\u7b49\u5f85\u89e6\u53d1\u6570\u636e"
    if value >= Decimal("80"):
        return "\u5f3a"
    if value >= Decimal("60"):
        return "\u4e2d"
    if value > Decimal("0"):
        return "\u5f31"
    return "\u7b49\u5f85\u89e6\u53d1\u6570\u636e"


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _clamp_score(value: Decimal, low: Decimal = Decimal("0"), high: Decimal = Decimal("100")) -> Decimal:
    return max(low, min(high, value))


def _score_payload(score: Decimal | None, *, state: str = "scored", gap_count: int = 0) -> dict[str, Any]:
    if score is None:
        return {
            "model_score": None,
            "model_score_label": "\u5f85\u8865",
            "score_state": state,
            "model_score_version": OBSERVATION_SCORE_VERSION,
        }
    adjusted = _clamp_score(score - min(Decimal("6"), Decimal(gap_count) * Decimal("2"))).quantize(Decimal("0.01"))
    if adjusted >= Decimal("80"):
        label = "\u9ad8"
    elif adjusted >= Decimal("60"):
        label = "\u4e2d"
    elif adjusted > Decimal("0"):
        label = "\u4f4e"
    else:
        label = "\u6781\u4f4e"
    return {
        "model_score": float(adjusted),
        "model_score_label": label,
        "score_state": "scored_with_gaps" if gap_count else state,
        "model_score_version": OBSERVATION_SCORE_VERSION,
    }


def _day1_observation_score(day1: dict[str, Any]) -> Decimal:
    seal = _decimal_or_none(day1.get("seal_commitment_score"))
    disagreement = _decimal_or_none(day1.get("disagreement_absorption_score"))
    fake_risk = _decimal_or_none(day1.get("fake_seal_trap_risk_score"))
    if seal is None and disagreement is None and fake_risk is None:
        return Decimal("50")
    seal_component = seal if seal is not None else Decimal("50")
    disagreement_component = disagreement if disagreement is not None else Decimal("50")
    fake_component = Decimal("100") - fake_risk if fake_risk is not None else Decimal("50")
    return _clamp_score(
        seal_component * Decimal("0.45")
        + disagreement_component * Decimal("0.35")
        + fake_component * Decimal("0.20"),
        Decimal("35"),
        Decimal("60"),
    )


def _observation_model_score(
    *,
    status: str,
    day1: dict[str, Any],
    valid_day2_watch: dict[str, Any] | None,
    valid_trigger: dict[str, Any] | None,
    post_entry: dict[str, Any] | None,
    day3: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
    gap_count: int,
) -> dict[str, Any]:
    if outcome:
        label = outcome.get("outcome_label")
        if label in {"relay_success", "t_board_relay_strong_success"}:
            return _score_payload(Decimal("92"), gap_count=gap_count)
        if label in {"relay_failed", "day2_board_open_after_entry_failed"}:
            return _score_payload(Decimal("5"), gap_count=gap_count)
        return _score_payload(None, state="data_wait", gap_count=gap_count)

    if day3:
        action = day3.get("day3_action")
        if action == "hold_open_limit":
            return _score_payload(_clamp_score(_decimal_or_none(day3.get("day3_open_seal_quality_score")) or Decimal("88"), Decimal("80"), Decimal("95")), gap_count=gap_count)
        if action == "exit_tail_no_limit":
            return _score_payload(Decimal("18"), gap_count=gap_count)
        if action == "data_blocked":
            return _score_payload(None, state="data_wait", gap_count=gap_count)
        return _score_payload(Decimal("70"), gap_count=gap_count)

    if post_entry:
        post_status = post_entry.get("post_entry_status")
        if post_status == "FAILED_AFTER_OPEN" or post_entry.get("outcome_label") == "day2_board_open_after_entry_failed":
            failure = _decimal_or_none(post_entry.get("control_failure_score")) or Decimal("100")
            return _score_payload(_clamp_score(Decimal("100") - failure, Decimal("0"), Decimal("15")), gap_count=gap_count)
        if post_status == "SEALED_TO_CLOSE":
            relay = _decimal_or_none((valid_trigger or {}).get("relay_consensus_score")) or Decimal("70")
            control = Decimal("100") - (_decimal_or_none(post_entry.get("control_failure_score")) or Decimal("0"))
            return _score_payload(_clamp_score(relay * Decimal("0.55") + control * Decimal("0.45"), Decimal("75"), Decimal("90")), gap_count=gap_count)
        if post_status == "DATA_INSUFFICIENT":
            return _score_payload(None, state="data_wait", gap_count=gap_count)
        return _score_payload(Decimal("45"), gap_count=gap_count)

    if valid_trigger:
        trigger_status = valid_trigger.get("entry_trigger_status")
        relay = _decimal_or_none(valid_trigger.get("relay_consensus_score"))
        if trigger_status == "triggered" and _trigger_has_bid_pressure(valid_trigger):
            return _score_payload(_clamp_score((relay or Decimal("60")) * Decimal("0.35"), Decimal("12"), Decimal("28")), gap_count=gap_count)
        if trigger_status == "triggered" and not _trigger_has_ask_sweep(valid_trigger):
            return _score_payload(None, state="data_wait", gap_count=gap_count)
        if trigger_status == "triggered":
            return _score_payload(_clamp_score(relay or Decimal("75"), Decimal("70"), Decimal("90")), gap_count=gap_count)
        if trigger_status == "data_blocked":
            return _score_payload(None, state="data_wait", gap_count=gap_count)
        if valid_trigger.get("not_trigger_reason") == "day2_bid_pressure_hit_buy_orders":
            return _score_payload(_clamp_score((relay or Decimal("50")) * Decimal("0.35"), Decimal("12"), Decimal("28")), gap_count=gap_count)
        return _score_payload(_clamp_score(relay or Decimal("24"), Decimal("18"), Decimal("32")), gap_count=gap_count)

    if valid_day2_watch:
        watch_status = valid_day2_watch.get("watch_status")
        if watch_status == "data_blocked":
            return _score_payload(None, state="data_wait", gap_count=gap_count)
        if watch_status == "near_limit_reached" or valid_day2_watch.get("near_limit_flag") is True:
            return _score_payload(_clamp_score(_decimal_or_none(valid_day2_watch.get("day2_near_limit_quality_score")) or Decimal("58"), Decimal("45"), Decimal("65")), gap_count=gap_count)
        return _score_payload(Decimal("38"), gap_count=gap_count)

    if status == "data_wait":
        return _score_payload(None, state="data_wait", gap_count=gap_count)
    return _score_payload(_day1_observation_score(day1), gap_count=gap_count)


def _build_observation_item(
    *,
    day1: dict[str, Any],
    day2_watch: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    post_entry: dict[str, Any] | None,
    day3: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
    hypothesis: dict[str, Any] | None,
) -> dict[str, Any]:
    stage = "Day1 \u5df2\u5165\u9009"
    status = "continue_watch"
    conclusion = "\u7b49\u5f85Day2\u5f00\u76d8\u540e\u6eda\u52a8\u89c2\u5bdf"
    next_observation = "Day2 09:30\u540e\u6bcf5\u5206\u949f\u89c2\u5bdf"
    key_reason = "\u9996\u65e5\u901a\u8fc7T\u5b57\u677f\u548c\u6d41\u901a\u5e02\u503c\u89c4\u5219"
    risk_tip = "Day2\u76d8\u53e3\u5c1a\u672a\u9a8c\u8bc1\uff0c\u98ce\u9669\u5f85\u5f00\u76d8\u6eda\u52a8\u76d1\u6d4b\u786e\u8ba4"
    data_notice = "\u4e8b\u5b9e\u5df2\u9f50"
    valid_day2_watch = day2_watch if day2_watch and _is_later_trading_stage(day1.get("trade_date"), day2_watch.get("day2_trade_date")) else None
    valid_trigger = trigger if trigger and _is_later_trading_stage(day1.get("trade_date"), trigger.get("day2_trade_date")) else None
    ignored_stage_reasons: list[str] = []
    if day2_watch and not valid_day2_watch:
        ignored_stage_reasons.append("Day2\u4ea4\u6613\u65e5\u5f85\u6821\u9a8c")
    if trigger and not valid_trigger:
        ignored_stage_reasons.append("Day2\u4ea4\u6613\u65e5\u5f85\u6821\u9a8c")
    post_entry = post_entry if valid_trigger and post_entry else None
    raw_day3 = day3
    day3 = raw_day3 if valid_trigger and raw_day3 and _is_later_trading_stage(valid_trigger.get("day2_trade_date"), raw_day3.get("day3_trade_date")) else None
    if valid_trigger and day3 is None and (raw_day3 or {}).get("day3_trade_date"):
        ignored_stage_reasons.append("Day3\u4ea4\u6613\u65e5\u5f85\u6821\u9a8c")
    outcome = outcome if valid_trigger and outcome else None
    hypothesis = hypothesis if valid_trigger and hypothesis else None

    if not valid_day2_watch and not valid_trigger and _day2_window_elapsed(day1.get("trade_date")):
        status = "data_wait"
        conclusion = "Day2 \u76d1\u6d4b\u6570\u636e\u672a\u843d\u5e93\uff0c\u6682\u4e0d\u7ee7\u7eed\u89c2\u5bdf"
        next_observation = "\u68c0\u67e5 Day2 \u4e94\u5206\u949f\u6293\u6570\u94fe\u8def"
        key_reason = "Day2 09:30-10:30 \u7a97\u53e3\u5df2\u8fc7\uff0c\u672a\u89c1\u771f\u5b9e\u4e94\u5206\u949f\u76d1\u6d4b\u4e8b\u5b9e"
        risk_tip = "Day2 \u771f\u5b9e\u6293\u6570\u65f6\u95f4\u672a\u63a8\u8fdb\uff0c\u4e0d\u80fd\u6309\u7ee7\u7eed\u89c2\u5bdf\u5c55\u793a"
        data_notice = "Day2 \u76d1\u6d4b\u7f3a\u5931"

    if valid_day2_watch and not valid_trigger:
        monitor_time = _display_time(valid_day2_watch.get("as_of_time"))
        monitor_label = f" {monitor_time}" if monitor_time else ""
        watch_status = valid_day2_watch.get("watch_status")
        stage = "Day2 \u89c2\u5bdf"
        if watch_status == "near_limit_reached" or valid_day2_watch.get("near_limit_flag") is True:
            status = "data_wait"
            conclusion = "Day2 \u5df2\u63a5\u8fd1\u6da8\u505c\uff0c\u7b49\u5f85\u76d8\u53e3\u786e\u8ba4"
            next_observation = "\u7ee7\u7eed\u786e\u8ba4\u662f\u5426\u4e70\u76d8\u4e3b\u52a8\u626b\u6389\u5356\u76d8"
            key_reason = f"Day2{monitor_label} \u4e94\u5206\u949f\u76d1\u6d4b\u5df2\u63a5\u8fd1\u6da8\u505c"
            risk_tip = "\u63a5\u8fd1\u6da8\u505c\u4f46\u76d8\u53e3\u65b9\u5411\u672a\u786e\u8ba4\uff0c\u6682\u4e0d\u786e\u8ba4\u63a5\u529b"
        elif watch_status == "data_blocked":
            status = "data_wait"
            conclusion = "Day2 \u6570\u636e\u4e0d\u5b8c\u6574\uff0c\u6682\u4e0d\u5224\u65ad"
            next_observation = "\u8865\u9f50 Day2 \u5206\u949f\u884c\u60c5\u548c\u76d8\u53e3\u4e8b\u5b9e\u540e\u590d\u6838"
            key_reason = f"Day2{monitor_label} \u4e94\u5206\u949f\u76d1\u6d4b\u6570\u636e\u4e0d\u8db3"
            risk_tip = "\u5173\u952e\u884c\u60c5\u6216\u76d8\u53e3\u4e8b\u5b9e\u7f3a\u5931\uff0c\u65e0\u6cd5\u786e\u8ba4\u63a5\u529b\u5f3a\u5ea6"
            data_notice = "\u5206\u949f\u884c\u60c5\u5f85\u8865"
        elif _day2_watch_window_complete(valid_day2_watch):
            status = "stopped"
            conclusion = "Day2 \u672a\u5230\u63a5\u529b\u70b9\uff0c\u505c\u6b62\u89c2\u5bdf"
            next_observation = "\u65e0\u9700\u7ee7\u7eed\u8ddf\u8e2a"
            key_reason = "Day2 09:30-10:30 \u4e94\u5206\u949f\u76d1\u6d4b\u672a\u63a5\u8fd1\u6da8\u505c"
            risk_tip = "Day2 \u5f00\u76d8\u524d1\u5c0f\u65f6\u672a\u63a5\u8fd1\u6da8\u505c\uff0c\u63a5\u529b\u5f3a\u5ea6\u4e0d\u8fbe\u6807"
        elif _day2_window_elapsed(day1.get("trade_date")):
            status = "data_wait"
            conclusion = "Day2 \u4e94\u5206\u949f\u76d1\u6d4b\u4e0d\u5b8c\u6574\uff0c\u6682\u505c\u89c2\u5bdf"
            next_observation = "\u8865\u9f50 Day2 \u540e\u7eed\u76d1\u6d4b\u70b9\u540e\u590d\u6838"
            key_reason = f"Day2{monitor_label} \u6709\u76d1\u6d4b\uff0c\u4f46 10:30 \u524d\u540e\u7eed\u4e94\u5206\u949f\u4e8b\u5b9e\u672a\u9f50"
            risk_tip = "Day2 \u76d1\u6d4b\u65f6\u95f4\u672a\u8986\u76d6\u5b8c\u6574\u7a97\u53e3\uff0c\u4e0d\u80fd\u7ee7\u7eed\u6309\u89c2\u5bdf\u4e2d\u5c55\u793a"
            data_notice = "Day2 \u76d1\u6d4b\u4e0d\u5b8c\u6574"
        else:
            status = "continue_watch"
            conclusion = "Day2 \u6eda\u52a8\u76d1\u6d4b\u4e2d"
            next_observation = "\u7ee7\u7eed\u6309\u4e94\u5206\u949f\u8282\u594f\u89c2\u5bdf"
            key_reason = f"Day2{monitor_label} \u4e94\u5206\u949f\u76d1\u6d4b\u5df2\u66f4\u65b0"
            risk_tip = "\u5c1a\u672a\u63a5\u8fd1\u6da8\u505c\uff0c\u63a5\u529b\u5f3a\u5ea6\u672a\u786e\u8ba4"

    if valid_trigger:
        trigger_status = valid_trigger.get("entry_trigger_status")
        stage = "Day2 \u89c2\u5bdf"
        if trigger_status == "triggered" and _trigger_has_bid_pressure(valid_trigger):
            status = "stopped"
            conclusion = "\u5356\u76d8\u4e3b\u52a8\u7838\u5411\u4e70\u76d8\uff0c\u505c\u6b62\u89c2\u5bdf"
            next_observation = "\u65e0\u9700\u7ee7\u7eed\u8ddf\u8e2a"
            key_reason = "Day2 \u63a5\u8fd1\u6da8\u505c\u65f6\u5356\u76d8\u4e3b\u52a8\u7838\u5411\u4e70\u76d8"
            risk_tip = "\u63a5\u8fd1\u6da8\u505c\u65f6\u5356\u76d8\u4e3b\u52a8\u7838\u5411\u4e70\u76d8\uff0c\u627f\u63a5\u8f6c\u5f31\uff0c\u8ffd\u9ad8\u98ce\u9669\u9ad8"
        elif trigger_status == "triggered" and not _trigger_has_ask_sweep(valid_trigger):
            status = "data_wait"
            conclusion = "\u76d8\u53e3\u65b9\u5411\u5f85\u786e\u8ba4\uff0c\u6682\u4e0d\u63d0\u793a\u4e70\u5165"
            next_observation = "\u8865\u9f50\u9010\u7b14\u65b9\u5411\u548c\u6210\u4ea4\u529b\u5ea6\u540e\u590d\u6838"
            key_reason = "Day2 \u63a5\u8fd1\u6da8\u505c\uff0c\u4f46\u4e70\u76d8\u626b\u5356\u76d8\u5c1a\u672a\u786e\u8ba4"
            risk_tip = "\u7f3a\u9010\u7b14\u65b9\u5411\u6216\u6210\u4ea4\u5f3a\u5ea6\uff0c\u65e0\u6cd5\u786e\u8ba4\u4e70\u76d8\u626b\u5356\u76d8"
            data_notice = "\u76d8\u53e3\u786e\u8ba4\u5f85\u8865"
        elif trigger_status == "triggered":
            status = "opportunity"
            conclusion = "\u63a5\u529b\u673a\u4f1a\u5df2\u89e6\u53d1\uff0c\u53ef\u4e70\u5165\u89c2\u5bdf"
            next_observation = "\u7ee7\u7eed\u6bcf5\u5206\u949f\u8ddf\u8e2a\u5c01\u677f\u5f3a\u5ea6\u548c\u5f00\u677f\u98ce\u9669"
            key_reason = "Day2 \u63a5\u8fd1\u6da8\u505c\uff0c\u4e70\u76d8\u4e3b\u52a8\u626b\u6389\u5356\u76d8"
            risk_tip = "\u4e70\u76d8\u626b\u5356\u76d8\u5df2\u786e\u8ba4\uff0c\u540e\u7eed\u53ea\u770b\u5c01\u677f\u80fd\u5426\u7ef4\u6301\u5230\u6536\u76d8"
        elif trigger_status == "data_blocked":
            status = "data_wait"
            conclusion = "\u6570\u636e\u4e0d\u8db3\uff0c\u5148\u4e0d\u5224\u65ad"
            next_observation = "\u8865\u9f50 Day2 \u5206\u949f\u884c\u60c5\u540e\u590d\u6838"
            key_reason = "Day2 \u6eda\u52a8\u76d1\u6d4b\u5173\u952e\u884c\u60c5\u672a\u9f50"
            risk_tip = "\u5206\u949f\u884c\u60c5\u6216\u76d8\u53e3\u5173\u952e\u4e8b\u5b9e\u7f3a\u5931\uff0c\u6682\u65e0\u6cd5\u8bc4\u4f30\u63a5\u529b\u98ce\u9669"
            data_notice = "\u5206\u949f\u884c\u60c5\u5f85\u8865"
        else:
            status = "stopped"
            conclusion = "Day2 \u672a\u5230\u63a5\u529b\u70b9\uff0c\u505c\u6b62\u89c2\u5bdf"
            next_observation = "\u65e0\u9700\u7ee7\u7eed\u8ddf\u8e2a"
            key_reason = "Day2 09:30-10:30 \u6bcf5\u5206\u949f\u76d1\u6d4b\u5747\u672a\u63a5\u8fd1\u6da8\u505c"
            risk_tip = "Day2 \u5f00\u76d8\u524d1\u5c0f\u65f6\u672a\u63a5\u8fd1\u6da8\u505c\uff0c\u65e5\u5185\u5f3a\u5ea6\u4e0d\u8fbe\u6807"

    if post_entry:
        post_status = post_entry.get("post_entry_status")
        stage = "\u5c01\u677f\u7ef4\u62a4"
        if post_status == "FAILED_AFTER_OPEN" or post_entry.get("outcome_label") == "day2_board_open_after_entry_failed":
            status = "stopped"
            conclusion = "\u89e6\u53d1\u540e\u5f00\u677f\uff0c\u505c\u6b62\u89c2\u5bdf"
            next_observation = "\u65e0\u9700\u7ee7\u7eed\u8ddf\u8e2a"
            key_reason = "Day2 \u89e6\u53d1\u540e\u5c01\u677f\u7ef4\u62a4\u51fa\u73b0\u5f00\u677f"
            risk_tip = "\u89e6\u53d1\u540e\u5f00\u677f\uff0c\u5c01\u677f\u7ef4\u62a4\u5931\u8d25\uff0cDay3\u9000\u51fa\u98ce\u9669\u5347\u9ad8"
        elif post_status:
            status = "continue_watch"
            conclusion = "\u5c01\u4f4f\u5230\u6536\u76d8\uff0cDay3 \u7ee7\u7eed\u89c2\u5bdf"
            next_observation = "Day3 \u5f00\u76d8\u770b\u662f\u5426\u7ee7\u7eed\u6da8\u505c\uff0c\u5c3e\u76d8\u786e\u8ba4\u53bb\u7559"
            key_reason = "Day2 \u89e6\u53d1\u540e\u5c01\u4f4f\u5230\u6536\u76d8"
            risk_tip = "Day2 \u672a\u5f00\u677f\uff0c\u98ce\u9669\u8f6c\u4e3aDay3\u5f00\u76d8\u548c\u5c3e\u76d8\u5f3a\u5ea6"

    if day3:
        action = day3.get("day3_action")
        stage = "Day3 \u53bb\u7559"
        if action == "hold_open_limit":
            status = "continue_watch"
            conclusion = "Day3 \u5f3a\u52bf\uff0c\u7ee7\u7eed\u7559\u610f"
            next_observation = "\u7ee7\u7eed\u89c2\u5bdf Day3 \u5c01\u677f\u8d28\u91cf"
            key_reason = "Day3 \u5f00\u76d8\u6da8\u505c"
            risk_tip = "Day3\u5f00\u76d8\u6da8\u505c\uff0c\u7ee7\u7eed\u89c2\u5bdf\u5c01\u5355\u8d28\u91cf\u548c\u5c3e\u76d8\u5f3a\u5ea6"
        elif action == "exit_tail_no_limit":
            status = "stopped"
            conclusion = "Day3 \u8f6c\u5f31\uff0c\u505c\u6b62\u89c2\u5bdf"
            next_observation = "\u65e0\u9700\u7ee7\u7eed\u8ddf\u8e2a"
            key_reason = "Day3 \u5c3e\u76d8\u672a\u6da8\u505c"
            risk_tip = "Day3\u5c3e\u76d8\u672a\u6da8\u505c\uff0c\u77ed\u7ebf\u5f3a\u5ea6\u8f6c\u5f31"
        elif action:
            conclusion = "Day3 \u7b49\u5f85\u786e\u8ba4"
            next_observation = "\u7b49\u5f85 Day3 \u5c3e\u76d8\u89c2\u5bdf"

    if outcome:
        label = outcome.get("outcome_label")
        if label in {"relay_success", "t_board_relay_strong_success"}:
            status = "completed"
            conclusion = "\u63a5\u529b\u5151\u73b0"
            next_observation = "\u8fdb\u5165\u590d\u76d8"
            key_reason = "\u7ed3\u679c\u6807\u7b7e\u5df2\u5b8c\u6210"
            risk_tip = "\u7ed3\u679c\u5df2\u5151\u73b0\uff0c\u8fdb\u5165\u590d\u76d8\uff0c\u4e0d\u518d\u8ffd\u8e2a\u65e5\u5185\u98ce\u9669"
        elif label in {"relay_failed", "day2_board_open_after_entry_failed"}:
            status = "stopped"
            conclusion = "\u63a5\u529b\u5931\u8d25\uff0c\u505c\u6b62\u89c2\u5bdf"
            next_observation = "\u8fdb\u5165\u590d\u76d8"
            key_reason = "\u7ed3\u679c\u6807\u7b7e\u5df2\u5b8c\u6210"
            risk_tip = "\u7ed3\u679c\u5df2\u5931\u8d25\uff0c\u8fdb\u5165\u590d\u76d8\uff0c\u53ea\u4fdd\u7559\u6837\u672c\u5f52\u56e0"

    labels = _gap_labels(day1, valid_day2_watch or {}, valid_trigger or {}, post_entry or {}, day3 or {}, outcome or {})
    if labels and status not in {"stopped", "completed"}:
        data_notice = "\u90e8\u5206\u4e8b\u5b9e\u5f85\u8865"
    if ignored_stage_reasons:
        data_notice = "\uff1b".join(ignored_stage_reasons)

    last_data_captured_at = _latest_time_value(outcome or {}, day3 or {}, post_entry or {}, valid_trigger or {}, valid_day2_watch or {}, day1)
    last_monitor_at = _last_monitor_time(
        day2_watch=valid_day2_watch,
        trigger=valid_trigger,
        post_entry=post_entry,
        day3=day3,
        outcome=outcome,
    )
    monitoring_summary = _monitoring_summary(
        status=status,
        valid_day2_watch=valid_day2_watch,
        valid_trigger=valid_trigger,
        post_entry=post_entry,
        day3=day3,
        outcome=outcome,
        last_monitor_at=last_monitor_at,
    )
    relay_strength_label = _relay_strength_label(valid_trigger.get("relay_consensus_score") if valid_trigger else None)
    if not valid_trigger and valid_day2_watch:
        if valid_day2_watch.get("watch_status") == "data_blocked":
            relay_strength_label = "\u5f85\u8865"
        elif valid_day2_watch.get("watch_status") == "near_limit_reached" or valid_day2_watch.get("near_limit_flag") is True:
            relay_strength_label = "\u5f85\u786e\u8ba4"
        else:
            relay_strength_label = "\u5f31"
    score_payload = _observation_model_score(
        status=status,
        day1=day1,
        valid_day2_watch=valid_day2_watch,
        valid_trigger=valid_trigger,
        post_entry=post_entry,
        day3=day3,
        outcome=outcome,
        gap_count=len(labels),
    )
    return {
        "observation_id": day1.get("day1_candidate_id"),
        "stock": {"symbol": day1.get("canonical_symbol"), "name": day1.get("stock_name")},
        "day1_trade_date": day1.get("trade_date"),
        "day2_trade_date": (valid_trigger or valid_day2_watch or {}).get("day2_trade_date"),
        "day2_trigger_time": valid_trigger.get("trigger_time") if valid_trigger else _display_time((valid_day2_watch or {}).get("as_of_time")),
        "day3_trade_date": day3.get("day3_trade_date") if day3 else None,
        "observation_status": status,
        "current_stage": stage,
        "current_conclusion": conclusion,
        "next_observation": next_observation,
        "key_reason": key_reason,
        **score_payload,
        "relay_strength_label": relay_strength_label,
        "risk_tip": risk_tip,
        "data_notice": data_notice,
        "data_gap_count": len(labels),
        "data_gap_labels": labels,
        "latest_snapshot_time": last_data_captured_at,
        "updated_at": last_data_captured_at,
        "latest_data_fetch_at": last_data_captured_at,
        "last_data_captured_at": last_data_captured_at,
        "display_update_at": last_data_captured_at,
        "last_model_output_at": None,
        "model_evaluated_at": None,
        "model_result_interval_minutes": MODEL_RESULT_INTERVAL_MINUTES,
        "projection_generated_at": _projection_generated_at(),
        "last_monitor_at": last_monitor_at,
        "monitor_interval_minutes": DEFAULT_MONITOR_INTERVAL_MINUTES,
        "monitoring_summary": monitoring_summary,
        "game_state_label": (hypothesis or {}).get("game_state_label"),
    }


def _observation_sort_key(item: dict[str, Any]) -> tuple[bool, Decimal, str]:
    score = _decimal_or_none(item.get("model_score"))
    latest = str(item.get("latest_snapshot_time") or item.get("day1_trade_date") or "")
    return (score is not None, score if score is not None else Decimal("-1"), latest)


def _snapshot_newer_than_item(snapshot: dict[str, Any], item: dict[str, Any]) -> bool:
    snapshot_time = _parse_iso_datetime(snapshot.get("captured_at") or snapshot.get("as_of_time"))
    item_time = _parse_iso_datetime(item.get("last_data_captured_at") or item.get("updated_at") or item.get("latest_snapshot_time"))
    return bool(snapshot_time and (item_time is None or snapshot_time >= item_time))


def _snapshot_interval_minutes(snapshot: dict[str, Any]) -> int:
    try:
        return int(snapshot.get("monitor_interval_minutes") or DEFAULT_MONITOR_INTERVAL_MINUTES)
    except (TypeError, ValueError):
        return DEFAULT_MONITOR_INTERVAL_MINUTES


def _is_model_result_snapshot(snapshot: dict[str, Any]) -> bool:
    return _snapshot_interval_minutes(snapshot) >= MODEL_RESULT_INTERVAL_MINUTES


def _monitor_snapshot_can_override_projection_fields(item: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    current_status = str(item.get("observation_status") or "").lower()
    snapshot_status = str(snapshot.get("observation_status") or "").lower()
    if current_status in {"stopped", "completed"} and snapshot_status != current_status:
        return False
    if current_status == "data_wait" and snapshot_status in {"continue_watch", "opportunity", ""}:
        return False
    return True


def _apply_projection_snapshot_metadata(item: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return item
    merged = dict(item)
    snapshot_time = snapshot.get("captured_at") or snapshot.get("as_of_time")
    merged["latest_projection_snapshot_at"] = snapshot_time
    merged["latest_projection_snapshot_id"] = snapshot.get("observation_snapshot_id")
    merged["latest_monitor_snapshot_id"] = snapshot.get("observation_snapshot_id")
    return merged


def _apply_monitor_snapshot(item: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot or not _is_model_result_snapshot(snapshot) or not _snapshot_newer_than_item(snapshot, item):
        return item
    merged = dict(item)
    if _monitor_snapshot_can_override_projection_fields(item, snapshot):
        for field in (
            "observation_status",
            "current_stage",
            "current_conclusion",
            "next_observation",
            "key_reason",
            "risk_tip",
            "model_score",
            "model_score_label",
            "score_state",
            "model_score_version",
            "relay_strength_label",
            "monitoring_summary",
            "data_gap_count",
            "data_gap_labels",
        ):
            if snapshot.get(field) is not None:
                merged[field] = snapshot.get(field)
    snapshot_time = snapshot.get("captured_at") or snapshot.get("as_of_time")
    merged["last_model_output_at"] = snapshot_time
    merged["model_evaluated_at"] = snapshot_time
    merged["model_result_interval_minutes"] = _snapshot_interval_minutes(snapshot)
    merged["latest_model_result_snapshot_id"] = snapshot.get("observation_snapshot_id")
    merged["latest_monitor_snapshot_id"] = snapshot.get("observation_snapshot_id")
    merged["monitor_interval_minutes"] = DEFAULT_MONITOR_INTERVAL_MINUTES
    return merged


def _snapshot_day_index(item: dict[str, Any], trade_date_value: Any) -> int:
    trade_date = _parse_iso_date(trade_date_value)
    day3 = _parse_iso_date(item.get("day3_trade_date"))
    day2 = _parse_iso_date(item.get("day2_trade_date"))
    day1 = _parse_iso_date(item.get("day1_trade_date"))
    if day3 and (trade_date is None or trade_date >= day3):
        return 3
    if day2 and (trade_date is None or trade_date >= day2):
        return 2
    if day1:
        return 1
    return 0


def _snapshot_trade_date(item: dict[str, Any], trade_date_value: Any) -> Any:
    if trade_date_value:
        return str(trade_date_value)[:10]
    return item.get("day3_trade_date") or item.get("day2_trade_date") or item.get("day1_trade_date")


def _observation_board_response(*, limit: int, include_monitor_snapshots: bool = True) -> dict[str, Any]:
    repo = _repository()
    status = repo.status()
    if status.get("repository_attached") is not True:
        return {
            "contract_kind": "t_board_relay_observation_board_v1",
            "repository_attached": False,
            "items": [],
            "excluded_counts": {},
            "warning_codes": status.get("warning_codes") or ["repository_not_attached"],
            "repository_status": status,
        }
    sort_window_limit = max(limit, OBSERVATION_SORT_WINDOW_LIMIT)
    day1_query = getattr(repo, "list_day1_observation_candidates", None)
    day1_items = day1_query(limit=sort_window_limit) if callable(day1_query) else repo.list_rows("day1_candidates", limit=sort_window_limit)
    observation_query = getattr(repo, "list_observation_rows", None)
    list_stage_rows = observation_query if callable(observation_query) else repo.list_rows
    day2_watch_items = list_stage_rows("day2_watch", limit=sort_window_limit)
    trigger_items = list_stage_rows("day2_triggers", limit=sort_window_limit)
    post_entry_items = list_stage_rows("post_entry_status", limit=sort_window_limit)
    day3_items = list_stage_rows("day3_decisions", limit=sort_window_limit)
    outcome_items = list_stage_rows("outcomes", limit=sort_window_limit)
    hypothesis_items = list_stage_rows("game_hypotheses", limit=sort_window_limit)
    monitor_snapshot_items: list[dict[str, Any]] = []
    snapshot_query = getattr(repo, "list_observation_monitor_snapshots", None)
    if include_monitor_snapshots and callable(snapshot_query):
        monitor_snapshot_items = snapshot_query(limit=sort_window_limit)

    latest_day2_watch_by_candidate: dict[str, dict[str, Any]] = {}
    for item in day2_watch_items:
        _keep_latest(latest_day2_watch_by_candidate, item.get("day1_candidate_id"), item)
    latest_trigger_by_candidate: dict[str, dict[str, Any]] = {}
    for item in trigger_items:
        _keep_latest(latest_trigger_by_candidate, item.get("day1_candidate_id"), item)
    latest_post_entry_by_trigger: dict[str, dict[str, Any]] = {}
    for item in post_entry_items:
        _keep_latest(latest_post_entry_by_trigger, item.get("entry_trigger_id"), item)
    latest_day3_by_trigger: dict[str, dict[str, Any]] = {}
    for item in day3_items:
        _keep_latest(latest_day3_by_trigger, item.get("entry_trigger_id"), item)
    latest_outcome_by_trigger: dict[str, dict[str, Any]] = {}
    latest_outcome_by_candidate: dict[str, dict[str, Any]] = {}
    for item in outcome_items:
        _keep_latest(latest_outcome_by_trigger, item.get("entry_trigger_id"), item)
        _keep_latest(latest_outcome_by_candidate, item.get("day1_candidate_id"), item)
    latest_hypothesis_by_entity: dict[str, dict[str, Any]] = {}
    for item in hypothesis_items:
        _keep_latest(latest_hypothesis_by_entity, item.get("related_entity_id"), item)
    latest_projection_snapshot_by_candidate: dict[str, dict[str, Any]] = {}
    latest_model_result_by_candidate: dict[str, dict[str, Any]] = {}
    for item in monitor_snapshot_items:
        if _is_model_result_snapshot(item):
            _keep_latest(latest_model_result_by_candidate, item.get("day1_candidate_id"), item)
        else:
            _keep_latest(latest_projection_snapshot_by_candidate, item.get("day1_candidate_id"), item)

    unique_day1: dict[str, dict[str, Any]] = {}
    for item in day1_items:
        key = item.get("day1_candidate_id") or f"{item.get('canonical_symbol')}|{item.get('trade_date')}|{item.get('created_at')}"
        _keep_latest(unique_day1, str(key), item)

    excluded_counts = {"day1_not_qualified": 0}
    items: list[dict[str, Any]] = []
    for day1 in unique_day1.values():
        if not _is_qualified_day1(day1):
            excluded_counts["day1_not_qualified"] += 1
            continue
        day2_watch = latest_day2_watch_by_candidate.get(str(day1.get("day1_candidate_id")))
        trigger = latest_trigger_by_candidate.get(str(day1.get("day1_candidate_id")))
        post_entry = latest_post_entry_by_trigger.get(str((trigger or {}).get("entry_trigger_id")))
        day3 = latest_day3_by_trigger.get(str((trigger or {}).get("entry_trigger_id")))
        outcome = latest_outcome_by_trigger.get(str((trigger or {}).get("entry_trigger_id"))) or latest_outcome_by_candidate.get(str(day1.get("day1_candidate_id")))
        hypothesis = (
            latest_hypothesis_by_entity.get(str((day3 or {}).get("day3_decision_id")))
            or latest_hypothesis_by_entity.get(str((trigger or {}).get("entry_trigger_id")))
        )
        observation_item = _build_observation_item(
            day1=day1,
            day2_watch=day2_watch,
            trigger=trigger,
            post_entry=post_entry,
            day3=day3,
            outcome=outcome,
            hypothesis=hypothesis,
        )
        projection_snapshot = latest_projection_snapshot_by_candidate.get(str(day1.get("day1_candidate_id")))
        model_snapshot = latest_model_result_by_candidate.get(str(day1.get("day1_candidate_id")))
        observation_item = _apply_projection_snapshot_metadata(observation_item, projection_snapshot)
        items.append(_apply_monitor_snapshot(observation_item, model_snapshot))
    items.sort(key=_observation_sort_key, reverse=True)
    return {
        "contract_kind": "t_board_relay_observation_board_v1",
        "repository_attached": True,
        "items": items[:limit],
        "excluded_counts": excluded_counts,
        "warning_codes": [],
        "repository_status": status,
    }


def _observation_monitor_snapshot_response(request: TBoardRelayRequest) -> dict[str, Any]:
    payload = _payload(request)
    limit = _positive_int(payload.get("limit"), OBSERVATION_SORT_WINDOW_LIMIT, upper=1000)
    monitor_interval_minutes = _positive_int(
        payload.get("monitor_interval_minutes"),
        DEFAULT_MONITOR_INTERVAL_MINUTES,
        upper=60,
    )
    captured_at = request.as_of_time_utc or _parse_iso_datetime(payload.get("captured_at")) or datetime.now(timezone.utc)
    as_of_time = request.as_of_time_utc or _parse_iso_datetime(payload.get("as_of_time_utc") or payload.get("as_of_time")) or captured_at
    trade_date_value = request.trade_date.isoformat() if request.trade_date else payload.get("trade_date")
    board = _observation_board_response(limit=limit, include_monitor_snapshots=False)
    items: list[dict[str, Any]] = []
    snapshot_kind = "model_result_30m" if monitor_interval_minutes >= MODEL_RESULT_INTERVAL_MINUTES else "projection_snapshot_5m"
    for item in board.get("items") or []:
        enriched = dict(item)
        enriched["snapshot_day_index"] = _snapshot_day_index(item, trade_date_value)
        enriched["snapshot_trade_date"] = _snapshot_trade_date(item, trade_date_value)
        enriched["monitor_interval_minutes"] = monitor_interval_minutes
        enriched["snapshot_kind"] = snapshot_kind
        if snapshot_kind == "model_result_30m":
            enriched["last_model_output_at"] = captured_at.isoformat()
            enriched["model_evaluated_at"] = captured_at.isoformat()
            enriched["model_result_interval_minutes"] = monitor_interval_minutes
        items.append(enriched)
    repo = _repository()
    persist = repo.persist_observation_monitor_snapshots(
        items=items,
        request_payload=_request_payload(request),
        run_id=_run_id(request, payload),
        as_of_time=as_of_time.isoformat(),
        captured_at=captured_at.isoformat(),
        trade_date=trade_date_value,
        monitor_interval_minutes=monitor_interval_minutes,
    )
    return {
        "model_name": "t_board_relay",
        "model_version": MODEL_VERSION,
        "structured_output": {
            "observation_monitor_snapshot": {
                "contract_kind": "t_board_relay_observation_monitor_snapshot_v1",
                "captured_at": captured_at.isoformat(),
                "as_of_time": as_of_time.isoformat(),
                "trade_date": trade_date_value,
                "monitor_interval_minutes": monitor_interval_minutes,
                "snapshot_kind": snapshot_kind,
                "snapshot_count": len(items),
                "items": items,
            },
            "repository_write": persist,
        },
        "jarvis_payload": {
            "can_place_order": False,
            "observation_only": True,
            "note": "observation monitor snapshot records model output only",
        },
        "contract_gaps": board.get("warning_codes") or [],
    }


@router.get("/health")
@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@router.get("/readyz")
def ready() -> dict[str, str]:
    status = _repository().status()
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "model_version": MODEL_VERSION,
        "repository_attached": str(status.get("repository_attached") is True).lower(),
    }


@prefixed_router.get("/healthz")
def prefixed_health() -> dict[str, str]:
    return health()


@prefixed_router.get("/readyz")
def prefixed_ready() -> dict[str, str]:
    return ready()


@prefixed_router.post("/day1/scan", response_model=ModelServiceResponse)
def day1_scan(request: TBoardRelayRequest) -> ModelServiceResponse:
    payload = _payload(request)
    body = response_for_day1_scan(_rows(request), request.trade_date.isoformat() if request.trade_date else None)
    body = _with_repository_write(stage="day1_scan", request=request, payload=payload, body=body)
    return ModelServiceResponse(**body)


@prefixed_router.get("/day1/candidates")
def day1_candidates(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return _repository_list_response("day1_candidates", limit=limit)


@prefixed_router.get("/observation-board")
def observation_board(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return _observation_board_response(limit=limit)


@prefixed_router.post("/observation-monitor/snapshot", response_model=ModelServiceResponse)
def observation_monitor_snapshot(request: TBoardRelayRequest) -> ModelServiceResponse:
    return ModelServiceResponse(**_observation_monitor_snapshot_response(request))


@prefixed_router.get("/observation-monitor/snapshots")
def observation_monitor_snapshots(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    repo = _repository()
    status = repo.status()
    snapshot_query = getattr(repo, "list_observation_monitor_snapshots", None)
    rows = snapshot_query(limit=limit) if status.get("repository_attached") is True and callable(snapshot_query) else []
    return {
        "contract_kind": "t_board_relay_observation_monitor_snapshot_repository_view_v1",
        "repository_attached": status.get("repository_attached") is True,
        "items": rows,
        "warning_codes": [] if rows or status.get("repository_attached") is True else status.get("warning_codes", []),
        "repository_status": status,
    }


@prefixed_router.get("/day1/candidates/{day1_candidate_id}")
def day1_candidate(day1_candidate_id: str) -> dict[str, Any]:
    repo = _repository()
    status = repo.status()
    item = repo.get_by_text_id("day1_candidate", day1_candidate_id) if status.get("repository_attached") is True else None
    return {
        "contract_kind": "t_board_relay_day1_candidate_repository_view_v1",
        "repository_attached": status.get("repository_attached") is True,
        "day1_candidate_id": day1_candidate_id,
        "item": item,
        "warning_codes": [] if item else ["repository_item_not_found"],
        "repository_status": status,
    }


@prefixed_router.post("/day2/watch", response_model=ModelServiceResponse)
def day2_watch(request: TBoardRelayRequest) -> ModelServiceResponse:
    payload = _payload(request)
    body = response_for_day2_watch(payload)
    body = _with_repository_write(stage="day2_watch", request=request, payload=payload, body=body)
    return ModelServiceResponse(**body)


@prefixed_router.post("/day2/trigger-check", response_model=ModelServiceResponse)
def day2_trigger_check(request: TBoardRelayRequest) -> ModelServiceResponse:
    payload = _payload(request)
    body = response_for_day2_trigger(payload)
    body = _with_repository_write(stage="day2_trigger", request=request, payload=payload, body=body)
    return ModelServiceResponse(**body)


@prefixed_router.get("/day2/triggers")
def day2_triggers(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return _repository_list_response("day2_triggers", limit=limit)


@prefixed_router.get("/day2/triggers/{entry_trigger_id}")
def day2_trigger(entry_trigger_id: str) -> dict[str, Any]:
    repo = _repository()
    status = repo.status()
    item = repo.get_by_text_id("day2_trigger", entry_trigger_id) if status.get("repository_attached") is True else None
    return {
        "contract_kind": "t_board_relay_day2_trigger_repository_view_v1",
        "repository_attached": status.get("repository_attached") is True,
        "entry_trigger_id": entry_trigger_id,
        "item": item,
        "warning_codes": [] if item else ["repository_item_not_found"],
        "repository_status": status,
    }


@prefixed_router.post("/post-entry/monitor", response_model=ModelServiceResponse)
def post_entry_monitor(request: TBoardRelayRequest) -> ModelServiceResponse:
    payload = _payload(request)
    body = response_for_post_entry_monitor(payload)
    body = _with_repository_write(stage="post_entry_monitor", request=request, payload=payload, body=body)
    return ModelServiceResponse(**body)


@prefixed_router.get("/post-entry/status")
def post_entry_status(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return _repository_list_response("post_entry_status", limit=limit)


@prefixed_router.post("/day3/exit-check", response_model=ModelServiceResponse)
def day3_exit_check(request: TBoardRelayRequest) -> ModelServiceResponse:
    payload = _payload(request)
    body = response_for_day3_exit(payload)
    body = _with_repository_write(stage="day3_exit", request=request, payload=payload, body=body)
    return ModelServiceResponse(**body)


@prefixed_router.get("/day3/decisions")
def day3_decisions(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return _repository_list_response("day3_decisions", limit=limit)


@prefixed_router.get("/outcomes")
def outcomes(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return _repository_list_response("outcomes", limit=limit)


@prefixed_router.post("/outcomes/build", response_model=ModelServiceResponse)
def outcome_build(request: TBoardRelayRequest) -> ModelServiceResponse:
    payload = _payload(request)
    body = response_for_outcome(payload)
    body = _with_repository_write(stage="outcome", request=request, payload=payload, body=body)
    return ModelServiceResponse(**body)


@prefixed_router.get("/game-hypotheses")
def game_hypotheses(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return _repository_list_response("game_hypotheses", limit=limit)


@prefixed_router.get("/repository/status")
def repository_status() -> dict[str, Any]:
    repo = _repository()
    status = repo.status()
    table_counts = repo.table_counts() if status.get("repository_attached") is True else {}
    return {
        "contract_kind": "t_board_relay_repository_status_v1",
        **status,
        "table_counts": table_counts,
    }


router.include_router(prefixed_router)
