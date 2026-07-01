from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from research_service.repository import ResearchPayloadRepository, jsonable, new_id, stable_hash
from research_service.schemas import ModelPayloadAssembleRequest, ModelPayloadAssembleResponse, SourceRef
from research_service.settings import Settings
from research_service.source_client import SourcePreflightClient
from research_service.task_registry import (
    ASSEMBLED_RESEARCH_PAYLOAD_STATUS,
    BLOCKED_DATA_GAP_STATUS,
    PAYLOAD_ASSEMBLY_SOURCE,
    RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
    TaskRequirement,
    get_requirement,
    list_requirements,
)

OPTIONAL_SOURCE_TABLES = {
    "source.stock_moneyflow_daily_v1",
    "source.event_news_v1",
}

T_RELAY_DAY2_TASKS = {
    "t_relay.day2.watch.rolling_5m",
    "t_relay.day2.trigger.rolling_5m",
}

T_RELAY_OBSERVATION_MONITOR_TASKS = {
    "t_relay.observation.monitor.snapshot_5m",
    "t_relay.live_result.compute_30m",
}

T_RELAY_DEGRADABLE_UPSTREAM_GAP_TASKS = {
    *T_RELAY_DAY2_TASKS,
    "t_relay.day2.post_entry.monitor",
    "t_relay.day3.exit.open",
    "t_relay.day3.exit.tail",
    "t_relay.outcome.build",
}

T_RELAY_DEGRADABLE_UPSTREAM_GAPS = {
    "source_gap:seal_order_snapshot_missing",
    "source_gap:dynamic_feature_bundle_missing",
    "source_gap:near_limit_order_absorption_missing",
}

CHINA_TZ = timezone(timedelta(hours=8))
T_RELAY_DAY2_TICK_QUERY_LIMIT = 10000
T_RELAY_DAY2_MONITOR_START_MINUTE = 9 * 60 + 30
T_RELAY_DAY2_MONITOR_END_MINUTE = 10 * 60 + 30
T_RELAY_DAY2_MONITOR_INTERVAL_MINUTES = 5
T_RELAY_DAY2_NEAR_LIMIT_THRESHOLD = Decimal("0.01")
HOT_SCORE_TASK = "hot.score.auction_confirmed"
HOT_DAILY_LOOKBACK_TABLES = {
    "source.daily_bar_v1",
    "source.adjusted_daily_bar_v1",
}
HOT_DAILY_LOOKBACK_LIMIT = 40
HOT_ADJUSTED_DAILY_FALLBACK_WARNING = "source_gap:daily_bar_missing_using_adjusted_daily_bar"
T_RELAY_UPSTREAM_AUDIT_PAYLOAD_FIELDS = {
    "request_payload",
    "result_payload",
    "game_hypothesis_payload",
    "evidence_json",
    "related_payload",
}


class PayloadAssemblyError(RuntimeError):
    pass


def requirements_payload() -> dict[str, Any]:
    return {
        "contract_kind": "research_model_payload_requirements_v1",
        "assembler_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
        "required_status": ASSEMBLED_RESEARCH_PAYLOAD_STATUS,
        "task_count": len(list_requirements()),
        "tasks": list_requirements(),
        "hard_rules": [
            "research-service reads only built source.* and allowed decision/research tables.",
            "research-service never calls providers and never reads raw_*.",
            "official release payloads require passed source-data-service /source/release/preflight.",
            "missing facts remain NULL/gap/block and are never replaced with 0, mock, sample payloads or GPT inference.",
            "scheduler remains a gate/dispatch service and does not assemble payload facts.",
        ],
    }


class ResearchPayloadAssembler:
    def __init__(
        self,
        repository: ResearchPayloadRepository,
        source_client: SourcePreflightClient,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.source_client = source_client
        self.settings = settings

    def assemble(self, request: ModelPayloadAssembleRequest) -> ModelPayloadAssembleResponse:
        task = get_requirement(request.task_code)
        if task is None:
            raise PayloadAssemblyError(f"unknown task_code: {request.task_code}")
        symbols = request.symbols or self.settings.default_symbol_list
        symbols = [item.upper() for item in symbols]
        if not symbols:
            raise PayloadAssemblyError("at least one symbol is required")
        checked_at = datetime.now(timezone.utc)
        run_id = request.run_id or f"research_assembly:{task.task_code}:{request.trade_date.isoformat()}"
        assembly_id = new_id("research_payload_assembly")

        source_rows, source_refs, gap_codes, source_warnings = self._collect_source(task, symbols, request)
        gap_codes, source_warnings = self._apply_hot_daily_fallback(task, symbols, source_rows, gap_codes, source_warnings)
        upstream_rows, upstream_refs, upstream_gaps, upstream_warnings = self._collect_upstream(task, symbols, request)
        gap_codes.extend(upstream_gaps)
        warnings: list[str] = [*source_warnings, *upstream_warnings]

        source_preflight: dict[str, Any] | None = None
        if task.source_preflight_required and task.model_phase:
            try:
                source_preflight = self.source_client.release_preflight(
                    model_code=task.model_code,
                    model_phase=task.model_phase,
                    trade_date=request.trade_date,
                    symbols=symbols,
                    decision_time=request.decision_time or request.as_of_time_utc,
                )
            except Exception as exc:  # noqa: BLE001
                source_preflight = {
                    "can_release_official_signal": False,
                    "coverage_status": "blocked",
                    "freshness_status": "blocked",
                    "blocking_reasons": ["source_preflight_unavailable"],
                    "error": str(exc),
                }
                gap_codes.append("source_gap:source_preflight_unavailable")
            if not self._preflight_passed(source_preflight):
                gap_codes.append("source_gap:source_preflight_not_passed")

        status = ASSEMBLED_RESEARCH_PAYLOAD_STATUS if not gap_codes else BLOCKED_DATA_GAP_STATUS
        payload = self._build_payload(
            task=task,
            request=request,
            symbols=symbols,
            source_rows=source_rows,
            upstream_rows=upstream_rows,
            source_refs=source_refs,
            upstream_refs=upstream_refs,
            source_preflight=source_preflight,
            status=status,
            gap_codes=sorted(set(gap_codes)),
            warnings=sorted(set(warnings)),
            run_id=run_id,
            assembly_id=assembly_id,
            checked_at=checked_at,
        )
        payload_hash = stable_hash(payload)
        payload["payload_hash"] = payload_hash

        audit_persisted = False
        if request.persist_audit:
            audit_persisted = self.repository.persist_assembly_audit(
                assembly_id=assembly_id,
                task_code=task.task_code,
                owner_service=task.owner_service,
                model_code=task.model_code,
                model_phase=task.model_phase,
                symbol=symbols[0] if len(symbols) == 1 else None,
                trade_date=request.trade_date.isoformat(),
                status=status,
                gap_codes=sorted(set(gap_codes)),
                source_refs=source_refs,
                upstream_refs=upstream_refs,
                payload_hash=payload_hash,
                payload=payload,
            )

        return ModelPayloadAssembleResponse(
            payload_assembly_contract=RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
            payload_assembly_status=status,  # type: ignore[arg-type]
            payload_assembly_source=PAYLOAD_ASSEMBLY_SOURCE,
            task_code=task.task_code,
            owner_service=task.owner_service,
            task_kind=task.task_kind,
            official_publish=task.official_publish,
            model_code=task.model_code,
            model_phase=task.model_phase,
            trade_date=request.trade_date.isoformat(),
            symbols=symbols,
            assembly_id=assembly_id,
            payload_hash=payload_hash,
            run_id=run_id,
            as_of_time_utc=(request.as_of_time_utc.isoformat() if request.as_of_time_utc else None),
            gap_codes=sorted(set(gap_codes)),
            warnings=warnings,
            source_refs=[SourceRef(**ref) for ref in source_refs],
            upstream_refs=[SourceRef(**ref) for ref in upstream_refs],
            source_preflight=source_preflight,
            payload=payload,
            audit_persisted=audit_persisted,
            checked_at=checked_at.isoformat(),
        )

    def _collect_source(
        self,
        task: TaskRequirement,
        symbols: list[str],
        request: ModelPayloadAssembleRequest,
    ) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], list[dict[str, Any]], list[str], list[str]]:
        rows_by_table: dict[str, dict[str, list[dict[str, Any]]]] = {}
        refs: list[dict[str, Any]] = []
        gaps: list[str] = []
        warnings: list[str] = []
        for table_name in task.source_tables:
            rows_by_table[table_name] = {}
            for symbol in symbols:
                limit = self._source_query_limit(task, table_name)
                rows = self.repository.fetch_source_rows(
                    table_name,
                    symbol=symbol,
                    trade_date=request.trade_date,
                    limit=limit,
                    before_or_on=self._source_query_before_or_on(task, table_name),
                )
                rows_by_table[table_name][symbol] = rows
                refs.append(self._source_ref(table_name, symbol, request.trade_date.isoformat(), rows))
                if not rows:
                    code = f"source_gap:{self._gap_slug(table_name)}_missing"
                    if table_name in OPTIONAL_SOURCE_TABLES:
                        warnings.append(code)
                    else:
                        gaps.append(code)
                    continue
                quality_gap = self._quality_gap(table_name, rows)
                if quality_gap:
                    if table_name in OPTIONAL_SOURCE_TABLES:
                        warnings.append(quality_gap)
                    else:
                        gaps.append(quality_gap)
        return rows_by_table, refs, gaps, warnings

    def _collect_upstream(
        self,
        task: TaskRequirement,
        symbols: list[str],
        request: ModelPayloadAssembleRequest,
    ) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], list[dict[str, Any]], list[str], list[str]]:
        rows_by_table: dict[str, dict[str, list[dict[str, Any]]]] = {}
        refs: list[dict[str, Any]] = []
        gaps: list[str] = []
        warnings: list[str] = []
        for table_name in task.upstream_tables:
            rows_by_table[table_name] = {}
            for symbol in symbols:
                lookup_trade_date = self._upstream_lookup_trade_date(task, table_name, request.trade_date)
                raw_rows = self._fetch_upstream_rows(task, table_name, symbol=symbol, trade_date=lookup_trade_date)
                rows = self._sanitize_upstream_rows(task, table_name, raw_rows)
                rows_by_table[table_name][symbol] = rows
                refs.append(self._source_ref(table_name, symbol, self._format_ref_trade_date(lookup_trade_date), rows))
                if not raw_rows:
                    gaps.append(f"source_gap:{self._gap_slug(table_name)}_missing")
                    continue
                hard_gaps, soft_gaps = self._classify_upstream_gaps(task, self._nested_gap_codes(raw_rows))
                gaps.extend(hard_gaps)
                warnings.extend(soft_gaps)
                if self._contains_sample_marker(raw_rows):
                    gaps.append("payload_gap:upstream_sample_payload_marker_present")
        return rows_by_table, refs, gaps, warnings

    def _fetch_upstream_rows(self, task: TaskRequirement, table_name: str, *, symbol: str, trade_date: Any) -> list[dict[str, Any]]:
        if task.owner_service == "hot-candidates-service" and table_name in {
            "decision_hot.hot_decision_case_v1",
            "decision_hot.hot_score_fact_v1",
            "decision_hot.hot_evidence_snapshot_v1",
            "decision_hot.hot_release_gate_audit_v1",
            "decision_hot.hot_signal_fact_v1",
        }:
            fetch_hot = getattr(self.repository, "fetch_hot_case_upstream_rows", None)
            if callable(fetch_hot):
                return fetch_hot(table_name, symbol=symbol, trade_date=trade_date)
        return self.repository.fetch_upstream_rows(table_name, symbol=symbol, trade_date=trade_date)

    def _upstream_lookup_trade_date(self, task: TaskRequirement, table_name: str, trade_date: Any) -> Any:
        if task.task_code in T_RELAY_DAY2_TASKS and table_name == "decision_t_relay.t_board_day1_candidate_v1":
            previous_trading_day = getattr(self.repository, "previous_trading_day", None)
            if callable(previous_trading_day):
                previous = previous_trading_day(trade_date)
                return previous or trade_date
            if hasattr(trade_date, "__sub__"):
                return trade_date - timedelta(days=1)
        return trade_date

    @classmethod
    def _sanitize_upstream_rows(cls, task: TaskRequirement, table_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if task.owner_service != "t-board-relay-service" or not table_name.startswith("decision_t_relay."):
            return rows
        sanitized: list[dict[str, Any]] = []
        for row in rows:
            sanitized.append({key: value for key, value in row.items() if key not in T_RELAY_UPSTREAM_AUDIT_PAYLOAD_FIELDS})
        return sanitized

    @staticmethod
    def _format_ref_trade_date(value: Any) -> str:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _build_payload(
        self,
        *,
        task: TaskRequirement,
        request: ModelPayloadAssembleRequest,
        symbols: list[str],
        source_rows: dict[str, dict[str, list[dict[str, Any]]]],
        upstream_rows: dict[str, dict[str, list[dict[str, Any]]]],
        source_refs: list[dict[str, Any]],
        upstream_refs: list[dict[str, Any]],
        source_preflight: dict[str, Any] | None,
        status: str,
        gap_codes: list[str],
        warnings: list[str],
        run_id: str,
        assembly_id: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        base = {
            "payload_assembly_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
            "payload_assembly_status": status,
            "payload_assembly_source": PAYLOAD_ASSEMBLY_SOURCE,
            "assembly_id": assembly_id,
            "task_code": task.task_code,
            "owner_service": task.owner_service,
            "model_code": task.model_code,
            "model_phase": task.model_phase,
            "trade_date": request.trade_date.isoformat(),
            "symbols": symbols,
            "symbol": symbols[0] if len(symbols) == 1 else None,
            "run_id": run_id,
            "as_of_time_utc": request.as_of_time_utc.isoformat() if request.as_of_time_utc else None,
            "source_gap_codes": gap_codes,
            "contract_gaps": gap_codes,
            "warning_codes": warnings,
            "source_refs": source_refs,
            "upstream_refs": upstream_refs,
            "source_preflight": source_preflight,
            "assembled_at": checked_at.isoformat(),
            "extra_context": request.extra_context,
        }
        if task.owner_service == "hot-candidates-service":
            base.update(self._hot_payload(task, symbols, source_rows, upstream_rows))
        elif task.owner_service == "candidate-memory-service":
            base.update(self._memory_payload(symbols, source_rows, upstream_rows))
        elif task.owner_service == "ambush-watchlist-service":
            base.update(self._ambush_payload(symbols, source_rows, upstream_rows))
        elif task.owner_service == "t-board-relay-service":
            base.update(self._t_relay_payload(task, request, symbols, source_rows, upstream_rows))
        return jsonable(base)

    def _hot_payload(self, task: TaskRequirement, symbols: list[str], source_rows: dict[str, dict[str, list[dict[str, Any]]]], upstream_rows: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
        symbol = symbols[0]
        daily = self._sort_daily_rows(source_rows.get("source.daily_bar_v1", {}).get(symbol, []))
        adjusted = self._sort_daily_rows(source_rows.get("source.adjusted_daily_bar_v1", {}).get(symbol, []))
        daily_source = "source.daily_bar_v1"
        daily_fallback_used = False
        if task.task_code == HOT_SCORE_TASK and not daily and adjusted:
            daily = self._adjusted_daily_as_daily_rows(adjusted)
            daily_source = "source.adjusted_daily_bar_v1"
            daily_fallback_used = True
        master = self._first(source_rows, "source.stock_master_v1", symbol)
        paid = self._first(source_rows, "source.ths_paid_limit_up_probability_v1", symbol)
        trade_status = self._first(source_rows, "source.trade_status_v1", symbol)
        quote = self._first(source_rows, "source.realtime_quote_v1", symbol)
        minute = self._first(source_rows, "source.minute_bar_v1", symbol)
        latest_daily = self._latest_daily_row(daily)
        instrument_id = self._first_value(
            latest_daily,
            master,
            trade_status,
            quote,
            minute,
            paid,
            keys=("instrument_id",),
        )
        p_limit_up = self._value(paid, "paid_limit_up_probability")
        build_batch_id = self._value(paid, "build_batch_id")
        return {
            "instrument_id": instrument_id,
            "symbol": symbol,
            "name": self._value(master, "stock_name"),
            "stock_name": self._value(master, "stock_name"),
            "batch_id": self._hot_batch_id(paid),
            "candidate_id": self._hot_candidate_id(paid, symbol),
            "candidate_source": "hot_candidates",
            "candidate_available_at": self._value(paid, "available_at"),
            "batch_available_at": self._value(paid, "available_at"),
            "p_limit_up": p_limit_up,
            "p_limit_up_raw": p_limit_up,
            "p_limit_up_calibrated": p_limit_up,
            "p_limit_up_source": "paid_ths_prior" if p_limit_up not in (None, "") else None,
            "p_limit_up_available_at": self._value(paid, "available_at"),
            "p_limit_up_model_version": self._value(paid, "primary_provider"),
            "p_limit_up_credential_version": build_batch_id,
            "source_rank_no": None,
            "limit_up_stage": None,
            "trade_date": self._value(paid, "trade_date") or self._value(latest_daily, "trade_date"),
            "daily_bars": daily,
            "daily_bar_source": daily_source,
            "daily_bar_fallback_used": daily_fallback_used,
            "adjusted_daily_bars": adjusted,
            "trade_status": trade_status,
            "stock_rank": self._first(source_rows, "source.stock_moneyflow_daily_v1", symbol),
            "moneyflow_context": self._first(source_rows, "source.stock_moneyflow_daily_v1", symbol),
            "news_events": source_rows.get("source.event_news_v1", {}).get(symbol, []),
            "minute_bars": source_rows.get("source.minute_bar_v1", {}).get(symbol, []),
            "realtime_quotes": source_rows.get("source.realtime_quote_v1", {}).get(symbol, []),
            "reference_entry_price": self._value(latest_daily, "close_price"),
            "upstream_model_facts": upstream_rows,
        }

    def _memory_payload(self, symbols: list[str], source_rows: dict[str, dict[str, list[dict[str, Any]]]], upstream_rows: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
        symbol = symbols[0]
        return {
            "symbol": symbol,
            "daily_bars": source_rows.get("source.daily_bar_v1", {}).get(symbol, []),
            "price_path": source_rows.get("source.adjusted_daily_bar_v1", {}).get(symbol, []),
            "moneyflow_context": self._first(source_rows, "source.stock_moneyflow_daily_v1", symbol),
            "tradability_context": self._first(source_rows, "source.trade_status_v1", symbol),
            "events": source_rows.get("source.event_news_v1", {}).get(symbol, []),
            "memory_age_days": None,
            "upstream_model_facts": upstream_rows,
        }

    def _ambush_payload(self, symbols: list[str], source_rows: dict[str, dict[str, list[dict[str, Any]]]], upstream_rows: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
        symbol = symbols[0]
        master = self._first(source_rows, "source.stock_master_v1", symbol)
        return {
            "instrument": {
                "instrument_id": symbol,
                "symbol": symbol,
                "exchange": self._value(master, "exchange"),
                "asset_type": "stock",
                "is_active": self._value(master, "list_status") in {None, "listed", "1"},
            },
            "bars": source_rows.get("source.adjusted_daily_bar_v1", {}).get(symbol, []) or source_rows.get("source.daily_bar_v1", {}).get(symbol, []),
            "weekly_bars": [],
            "as_of_trading_day": self._infer_trade_date(source_rows, symbol),
            "moneyflow_context": self._first(source_rows, "source.stock_moneyflow_daily_v1", symbol),
            "tradability_context": self._first(source_rows, "source.trade_status_v1", symbol),
            "event_news_context": source_rows.get("source.event_news_v1", {}).get(symbol, []),
            "upstream_model_facts": upstream_rows,
        }

    def _t_relay_payload(
        self,
        task: TaskRequirement,
        request: ModelPayloadAssembleRequest,
        symbols: list[str],
        source_rows: dict[str, dict[str, list[dict[str, Any]]]],
        upstream_rows: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> dict[str, Any]:
        if task.task_code in T_RELAY_OBSERVATION_MONITOR_TASKS:
            monitor_interval_minutes = (
                30
                if task.task_code == "t_relay.live_result.compute_30m"
                else T_RELAY_DAY2_MONITOR_INTERVAL_MINUTES
            )
            payload = {
                "trade_date": request.trade_date.isoformat(),
                "limit": 500,
                "monitor_interval_minutes": monitor_interval_minutes,
                "as_of_time_utc": request.as_of_time_utc.isoformat() if request.as_of_time_utc else None,
                "symbols": symbols,
                "scheduler_context": request.extra_context.get("scheduler_materialized_instance")
                if isinstance(request.extra_context, dict)
                else None,
            }
            if task.task_code == "t_relay.live_result.compute_30m":
                payload["result_kind"] = "model_result_30m"
            return {"payload": payload}
        rows = [self._t_relay_symbol_payload(task, request, symbol, source_rows, upstream_rows) for symbol in symbols]
        if task.task_code == "t_relay.day1.scan.close":
            return {"rows": rows}
        return {
            "payload": rows[0] if rows else {},
        }

    def _t_relay_symbol_payload(
        self,
        task: TaskRequirement,
        request: ModelPayloadAssembleRequest,
        symbol: str,
        source_rows: dict[str, dict[str, list[dict[str, Any]]]],
        upstream_rows: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> dict[str, Any]:
        master = self._first(source_rows, "source.stock_master_v1", symbol)
        daily = self._first(source_rows, "source.daily_bar_v1", symbol)
        limit_price = self._first(source_rows, "source.limit_price_v1", symbol)
        limit_event = self._first(source_rows, "source.limit_event_v1", symbol)
        quote = self._first(source_rows, "source.realtime_quote_v1", symbol)
        minute_bars = source_rows.get("source.minute_bar_v1", {}).get(symbol, [])
        trade_ticks = source_rows.get("source.trade_tick_v1", {}).get(symbol, [])
        up_limit_price = self._value(limit_price, "up_limit_price")
        monitor_context = self._select_day2_monitor_bar(minute_bars, up_limit_price)
        watch_bar = monitor_context.get("row") or self._first_row(minute_bars)
        last_price_at_watch = self._value(watch_bar, "close_price") or self._value(quote, "latest_price")
        distance = monitor_context.get("distance_to_up_limit_pct") or self._distance_to_limit(last_price_at_watch, up_limit_price)
        day1_candidate = self._first_upstream_fact(upstream_rows, "decision_t_relay.t_board_day1_candidate_v1", symbol)
        watch_snapshot = self._first_upstream_fact(upstream_rows, "decision_t_relay.t_board_day2_watch_snapshot_v1", symbol)
        entry_trigger = self._first_upstream_fact(upstream_rows, "decision_t_relay.t_board_day2_entry_trigger_v1", symbol)
        post_entry_monitor = self._first_upstream_fact(upstream_rows, "decision_t_relay.t_board_post_entry_monitor_v1", symbol)
        day3_decision = self._first_upstream_fact(upstream_rows, "decision_t_relay.t_board_day3_exit_decision_v1", symbol)
        up_limit_price = up_limit_price or self._value(entry_trigger, "up_limit_price") or self._value(post_entry_monitor, "up_limit_price")
        tick_context = self._trade_tick_context(trade_ticks, monitor_context.get("monitor_check_time"))
        payload = {
            "symbol": symbol,
            "canonical_symbol": symbol,
            "stock_name": self._value(master, "stock_name"),
            "name": self._value(master, "stock_name"),
            "trade_date": self._value(daily, "trade_date") or self._infer_trade_date(source_rows, symbol),
            "open_price": self._value(daily, "open_price"),
            "high_price": self._value(daily, "high_price"),
            "low_price": self._value(daily, "low_price"),
            "close_price": self._value(daily, "close_price"),
            "pre_close_price": self._value(limit_price, "pre_close_price") or self._value(daily, "pre_close_price"),
            "up_limit_price": up_limit_price,
            "down_limit_price": self._value(limit_price, "down_limit_price"),
            "float_market_cap": self._value(quote, "float_market_cap"),
            "limit_event_type": self._value(limit_event, "limit_event_type"),
            "is_one_word_board": self._value(limit_event, "is_one_word_board"),
            "is_break_limit": self._value(limit_event, "is_break_limit"),
            "close_on_limit_flag": self._value(limit_event, "close_on_limit_flag"),
            "limit_open_count": self._value(limit_event, "limit_open_count"),
            "day1_candidate": day1_candidate,
            "day1_candidate_id": self._value(day1_candidate, "day1_candidate_id"),
            "day1_candidate_status": self._value(day1_candidate, "candidate_status"),
            "watch_snapshot": watch_snapshot,
            "entry_trigger": entry_trigger,
            "post_entry_monitor": post_entry_monitor,
            "day3_decision": day3_decision,
            "entry_trigger_id": self._value(entry_trigger, "entry_trigger_id")
            or self._value(post_entry_monitor, "entry_trigger_id")
            or self._value(day3_decision, "entry_trigger_id"),
            "day2_trade_date": self._infer_trade_date(source_rows, symbol),
            "as_of_time": self._value(watch_bar, "bar_time"),
            "watch_window_start_time": "09:30:00",
            "watch_window_end_time": "10:30:00",
            "monitor_interval_minutes": T_RELAY_DAY2_MONITOR_INTERVAL_MINUTES,
            "monitor_check_time": monitor_context.get("monitor_check_time"),
            "first_qualified_monitor_time": monitor_context.get("first_qualified_monitor_time"),
            "last_price_at_watch": last_price_at_watch,
            "last_price_at_trigger": last_price_at_watch,
            "trigger_time": monitor_context.get("first_qualified_monitor_time") or monitor_context.get("monitor_check_time"),
            "distance_to_up_limit_pct": distance,
            "day2_distance_to_up_limit_pct": distance,
            "rolling_near_limit_triggered": monitor_context.get("first_qualified_monitor_time") is not None,
            "monitor_bar_count": monitor_context.get("monitor_bar_count"),
            "minute_bars": minute_bars,
            "trade_ticks": trade_ticks,
            "upstream_model_facts": upstream_rows,
        }
        payload.update(tick_context)
        if task.task_code == "t_relay.day2.trigger.rolling_5m" and watch_snapshot:
            payload["watch_snapshot"] = self._merge_watch_snapshot(watch_snapshot, payload)
        if task.task_code == "t_relay.day2.post_entry.monitor":
            payload.update(
                self._post_entry_monitor_payload(
                    minute_bars=minute_bars,
                    limit_event=limit_event,
                    entry_trigger=entry_trigger,
                    up_limit_price=up_limit_price,
                    as_of_time_utc=request.as_of_time_utc,
                )
            )
        if task.task_code in {"t_relay.day3.exit.open", "t_relay.day3.exit.tail"}:
            payload.update(
                self._day3_exit_payload(
                    task_code=task.task_code,
                    minute_bars=minute_bars,
                    post_entry_monitor=post_entry_monitor,
                    up_limit_price=up_limit_price,
                )
            )
        if task.task_code == "t_relay.outcome.build":
            payload["post_entry_monitor"] = post_entry_monitor
            payload["day3_decision"] = day3_decision
        return payload

    @staticmethod
    def _preflight_passed(payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        blocking = payload.get("blocking_reasons") or []
        return (
            payload.get("can_release_official_signal") is True
            and isinstance(blocking, list)
            and not blocking
            and str(payload.get("coverage_status") or "passed").lower() in {"passed", "ready", "ok"}
            and str(payload.get("freshness_status") or "passed").lower() in {"passed", "ready", "ok"}
        )

    def _source_query_limit(self, task: TaskRequirement, table_name: str) -> int:
        if task.task_code == HOT_SCORE_TASK and table_name in HOT_DAILY_LOOKBACK_TABLES:
            return max(self.settings.source_query_limit_daily, HOT_DAILY_LOOKBACK_LIMIT)
        if table_name == "source.trade_tick_v1" and task.task_code in T_RELAY_DAY2_TASKS:
            return max(self.settings.source_query_limit_intraday, T_RELAY_DAY2_TICK_QUERY_LIMIT)
        if table_name in {"source.minute_bar_v1", "source.trade_tick_v1"}:
            return self.settings.source_query_limit_intraday
        return self.settings.source_query_limit_daily

    @staticmethod
    def _source_query_before_or_on(task: TaskRequirement, table_name: str) -> bool:
        return task.task_code == HOT_SCORE_TASK and table_name in HOT_DAILY_LOOKBACK_TABLES

    @classmethod
    def _classify_upstream_gaps(cls, task: TaskRequirement, codes: list[str]) -> tuple[list[str], list[str]]:
        hard: list[str] = []
        soft: list[str] = []
        for code in codes:
            if task.task_code in T_RELAY_DEGRADABLE_UPSTREAM_GAP_TASKS and code in T_RELAY_DEGRADABLE_UPSTREAM_GAPS:
                soft.append(code)
            else:
                hard.append(code)
        return sorted(set(hard)), sorted(set(soft))

    @classmethod
    def _apply_hot_daily_fallback(
        cls,
        task: TaskRequirement,
        symbols: list[str],
        source_rows: dict[str, dict[str, list[dict[str, Any]]]],
        gaps: list[str],
        warnings: list[str],
    ) -> tuple[list[str], list[str]]:
        if task.task_code != HOT_SCORE_TASK:
            return gaps, warnings
        daily_gap = "source_gap:daily_bar_missing"
        if daily_gap not in gaps:
            return gaps, warnings

        daily_by_symbol = source_rows.get("source.daily_bar_v1", {})
        adjusted_by_symbol = source_rows.get("source.adjusted_daily_bar_v1", {})
        missing_symbols = [symbol for symbol in symbols if not daily_by_symbol.get(symbol)]
        fallback_symbols = [
            symbol
            for symbol in missing_symbols
            if adjusted_by_symbol.get(symbol)
            and cls._quality_gap("source.adjusted_daily_bar_v1", adjusted_by_symbol[symbol]) is None
        ]
        if missing_symbols and len(fallback_symbols) == len(missing_symbols):
            gaps = [code for code in gaps if code != daily_gap]
            warnings = [*warnings, HOT_ADJUSTED_DAILY_FALLBACK_WARNING]
        return gaps, warnings

    @staticmethod
    def _source_ref(table_name: str, symbol: str | None, trade_date: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        first = rows[0] if rows else {}
        return {
            "table_name": table_name,
            "symbol": symbol,
            "trade_date": trade_date,
            "row_count": len(rows),
            "source_quality_status": first.get("source_quality_status") or first.get("quality_status"),
            "available_at": first.get("available_at"),
            "lineage_id": first.get("lineage_id"),
            "build_batch_id": first.get("build_batch_id"),
        }

    @classmethod
    def _quality_gap(cls, table_name: str, rows: list[dict[str, Any]]) -> str | None:
        for row in rows[:1]:
            quality = row.get("source_quality_status") or row.get("quality_status")
            if quality and str(quality).lower() not in {"usable", "passed", "ok", "ready"}:
                return f"source_gap:{cls._gap_slug(table_name)}_quality_{quality}"
            if "available_at" in row and not row.get("available_at"):
                return f"source_gap:{cls._gap_slug(table_name)}_available_at_missing"
        return None

    @classmethod
    def _nested_gap_codes(cls, value: Any) -> list[str]:
        codes: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).lower()
                if key_text in {"source_gap_codes", "gap_codes", "contract_gaps"} or key_text.endswith("_gap_codes"):
                    codes.extend(cls._string_values(item))
                elif key_text == "blocking_reasons":
                    codes.extend([text for text in cls._string_values(item) if text.startswith("source_gap:")])
                codes.extend(cls._nested_gap_codes(item))
        elif isinstance(value, list):
            for item in value:
                codes.extend(cls._nested_gap_codes(item))
        elif isinstance(value, str) and value.startswith(("source_gap:", "payload_gap:")):
            codes.append(value)
        return sorted(set(codes))

    @classmethod
    def _contains_sample_marker(cls, value: Any) -> bool:
        if isinstance(value, dict):
            return any(cls._contains_sample_marker(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._contains_sample_marker(item) for item in value)
        if not isinstance(value, str):
            return False
        text = value.lower()
        return (
            "scheduler_live_dispatch_contract_sample" in text
            or text.startswith("sample-")
            or text.startswith("sample_")
        )

    @staticmethod
    def _first_upstream_fact(
        upstream_rows: dict[str, dict[str, list[dict[str, Any]]]],
        table_name: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        row = ResearchPayloadAssembler._first_row(upstream_rows.get(table_name, {}).get(symbol, []))
        if not row:
            return None
        result_payload = row.get("result_payload")
        if isinstance(result_payload, dict):
            return jsonable(row | result_payload)
        return row

    @staticmethod
    def _merge_watch_snapshot(watch_snapshot: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        merged = dict(watch_snapshot)
        for key in (
            "up_limit_price",
            "last_price_at_watch",
            "distance_to_up_limit_pct",
            "near_limit_flag",
            "monitor_interval_minutes",
            "monitor_check_time",
            "first_qualified_monitor_time",
            "market_context_status",
            "source_gap_codes",
            "dynamic_feature_run_id",
        ):
            if merged.get(key) is None and fallback.get(key) is not None:
                merged[key] = fallback[key]
        return merged

    @classmethod
    def _select_bar_at_time(cls, rows: list[dict[str, Any]], target: time) -> dict[str, Any] | None:
        best: tuple[int, dict[str, Any]] | None = None
        target_minutes = target.hour * 60 + target.minute
        for row in rows:
            dt = cls._parse_datetime(row.get("bar_time") or row.get("event_time"))
            if dt is None:
                continue
            local_dt = dt.astimezone(CHINA_TZ) if dt.tzinfo else dt
            minute_of_day = local_dt.hour * 60 + local_dt.minute
            delta = abs(minute_of_day - target_minutes)
            if best is None or delta < best[0]:
                best = (delta, row)
        if best is not None:
            return best[1]
        return cls._first_row(rows)

    @classmethod
    def _post_entry_monitor_payload(
        cls,
        *,
        minute_bars: list[dict[str, Any]],
        limit_event: dict[str, Any] | None,
        entry_trigger: dict[str, Any] | None,
        up_limit_price: Any,
        as_of_time_utc: datetime | None,
    ) -> dict[str, Any]:
        entry_time = cls._value(entry_trigger, "trigger_time")
        entry_minutes = cls._time_text_to_minutes(entry_time) or T_RELAY_DAY2_MONITOR_START_MINUTE
        end_minutes = cls._datetime_to_local_minutes(as_of_time_utc) or (15 * 60)
        if end_minutes < entry_minutes:
            end_minutes = entry_minutes
        bars = cls._bars_between_minutes(minute_bars, entry_minutes, end_minutes)
        latest_bar = bars[-1] if bars else cls._first_row(minute_bars)
        limit = cls._decimal(up_limit_price)

        opened_bar: dict[str, Any] | None = None
        lowest_price: Decimal | None = None
        if limit is not None:
            for bar in bars:
                price = cls._bar_price(bar)
                if price is None:
                    continue
                lowest_price = price if lowest_price is None else min(lowest_price, price)
                if price < limit and opened_bar is None:
                    opened_bar = bar

        latest_price = cls._bar_price(latest_bar)
        close_on_limit: bool | Any | None = None
        if latest_price is not None and limit is not None:
            close_on_limit = latest_price >= limit
        elif limit_event:
            close_on_limit = limit_event.get("close_on_limit_flag")

        entry_price = cls._decimal(cls._value(entry_trigger, "last_price_at_trigger")) or limit
        max_drawdown: str | None = None
        if lowest_price is not None and entry_price not in (None, Decimal("0")):
            max_drawdown = str(((lowest_price - entry_price) / entry_price).quantize(Decimal("0.000001")))

        return {
            "entry_trigger_id": cls._value(entry_trigger, "entry_trigger_id"),
            "day1_candidate_id": cls._value(entry_trigger, "day1_candidate_id"),
            "day2_trade_date": cls._value(entry_trigger, "day2_trade_date"),
            "entry_time": entry_time,
            "entry_price": cls._value(entry_trigger, "last_price_at_trigger"),
            "post_entry_board_opened": (opened_bar is not None) if bars and limit is not None else None,
            "first_board_open_time_after_entry": cls._bar_time_label(opened_bar),
            "board_open_count_after_entry": sum(
                1
                for bar in bars
                if limit is not None and (price := cls._bar_price(bar)) is not None and price < limit
            ),
            "lowest_price_after_entry": str(lowest_price) if lowest_price is not None else None,
            "max_drawdown_after_entry": max_drawdown,
            "close_price": str(latest_price) if latest_price is not None else None,
            "close_on_limit_flag": close_on_limit,
        }

    @classmethod
    def _day3_exit_payload(
        cls,
        *,
        task_code: str,
        minute_bars: list[dict[str, Any]],
        post_entry_monitor: dict[str, Any] | None,
        up_limit_price: Any,
    ) -> dict[str, Any]:
        limit = cls._decimal(up_limit_price)
        open_bar = cls._first_bar_between_minutes(minute_bars, 9 * 60 + 25, 9 * 60 + 35)
        tail_bar = cls._latest_bar_between_minutes(minute_bars, 14 * 60 + 40, 14 * 60 + 55)
        open_price = cls._bar_price(open_bar)
        tail_price = cls._bar_price(tail_bar)
        payload = {
            "entry_trigger_id": cls._value(post_entry_monitor, "entry_trigger_id"),
            "day2_trade_date": cls._value(post_entry_monitor, "day2_trade_date"),
            "day3_open_price": str(open_price) if open_price is not None else None,
            "day3_up_limit_price": up_limit_price,
            "day3_open_limit_up_flag": (open_price >= limit) if open_price is not None and limit is not None else None,
            "post_entry_monitor": post_entry_monitor,
        }
        if task_code == "t_relay.day3.exit.tail":
            payload.update(
                {
                    "day3_tail_price": str(tail_price) if tail_price is not None else None,
                    "day3_tail_limit_up_flag": (tail_price >= limit) if tail_price is not None and limit is not None else None,
                    "tail_limit_up_flag": (tail_price >= limit) if tail_price is not None and limit is not None else None,
                }
            )
        return payload

    @classmethod
    def _select_day2_monitor_bar(cls, rows: list[dict[str, Any]], up_limit_price: Any) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        for row in rows:
            dt = cls._parse_datetime(row.get("bar_time") or row.get("event_time"))
            if dt is None:
                continue
            local_dt = dt.astimezone(CHINA_TZ) if dt.tzinfo else dt
            minute_of_day = local_dt.hour * 60 + local_dt.minute
            if minute_of_day < T_RELAY_DAY2_MONITOR_START_MINUTE or minute_of_day > T_RELAY_DAY2_MONITOR_END_MINUTE:
                continue
            if (minute_of_day - T_RELAY_DAY2_MONITOR_START_MINUTE) % T_RELAY_DAY2_MONITOR_INTERVAL_MINUTES != 0:
                continue
            price = row.get("close_price") or row.get("latest_price") or row.get("price")
            candidates.append(
                {
                    "row": row,
                    "local_dt": local_dt,
                    "distance_to_up_limit_pct": cls._distance_to_limit(price, up_limit_price),
                }
            )
        candidates.sort(key=lambda item: item["local_dt"])
        first_qualified: dict[str, Any] | None = None
        for item in candidates:
            distance = cls._decimal(item.get("distance_to_up_limit_pct"))
            if distance is not None and distance <= T_RELAY_DAY2_NEAR_LIMIT_THRESHOLD:
                first_qualified = item
                break
        selected = first_qualified or (candidates[-1] if candidates else None)
        if selected is None:
            return {
                "row": cls._first_row(rows),
                "monitor_check_time": None,
                "first_qualified_monitor_time": None,
                "distance_to_up_limit_pct": None,
                "monitor_bar_count": 0,
            }
        check_time = selected["local_dt"].time().replace(microsecond=0).isoformat()
        qualified_time = (
            first_qualified["local_dt"].time().replace(microsecond=0).isoformat()
            if first_qualified
            else None
        )
        return {
            "row": selected["row"],
            "monitor_check_time": check_time,
            "first_qualified_monitor_time": qualified_time,
            "distance_to_up_limit_pct": selected.get("distance_to_up_limit_pct"),
            "monitor_bar_count": len(candidates),
        }

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value:
            return None
        text = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @classmethod
    def _datetime_to_local_minutes(cls, value: Any) -> int | None:
        dt = cls._parse_datetime(value)
        if dt is None:
            return None
        local_dt = dt.astimezone(CHINA_TZ) if dt.tzinfo else dt
        return local_dt.hour * 60 + local_dt.minute

    @staticmethod
    def _time_text_to_minutes(value: Any) -> int | None:
        if not value:
            return None
        try:
            hour, minute, *_ = str(value).split(":")
            return int(hour) * 60 + int(minute)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _bars_between_minutes(cls, rows: list[dict[str, Any]], start_minutes: int, end_minutes: int) -> list[dict[str, Any]]:
        bars: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            minute_of_day = cls._datetime_to_local_minutes(row.get("bar_time") or row.get("event_time"))
            if minute_of_day is None:
                continue
            if start_minutes <= minute_of_day <= end_minutes:
                bars.append((minute_of_day, row))
        return [row for _, row in sorted(bars, key=lambda item: item[0])]

    @classmethod
    def _first_bar_between_minutes(cls, rows: list[dict[str, Any]], start_minutes: int, end_minutes: int) -> dict[str, Any] | None:
        bars = cls._bars_between_minutes(rows, start_minutes, end_minutes)
        return bars[0] if bars else None

    @classmethod
    def _latest_bar_between_minutes(cls, rows: list[dict[str, Any]], start_minutes: int, end_minutes: int) -> dict[str, Any] | None:
        bars = cls._bars_between_minutes(rows, start_minutes, end_minutes)
        return bars[-1] if bars else None

    @classmethod
    def _bar_price(cls, row: dict[str, Any] | None) -> Decimal | None:
        if not row:
            return None
        return cls._decimal(row.get("close_price") or row.get("latest_price") or row.get("price"))

    @classmethod
    def _bar_time_label(cls, row: dict[str, Any] | None) -> str | None:
        if not row:
            return None
        dt = cls._parse_datetime(row.get("bar_time") or row.get("event_time"))
        if dt is None:
            return None
        local_dt = dt.astimezone(CHINA_TZ) if dt.tzinfo else dt
        return local_dt.time().replace(microsecond=0).isoformat()

    @classmethod
    def _distance_to_limit(cls, price: Any, up_limit_price: Any) -> str | None:
        current = cls._decimal(price)
        limit = cls._decimal(up_limit_price)
        if current is None or limit in (None, Decimal("0")):
            return None
        return str(((limit - current) / limit).quantize(Decimal("0.000001")))

    @classmethod
    def _trade_tick_context(cls, rows: list[dict[str, Any]], monitor_check_time: Any = None) -> dict[str, Any]:
        buy_amount = Decimal("0")
        sell_amount = Decimal("0")
        included = 0
        window_end_minutes = T_RELAY_DAY2_MONITOR_END_MINUTE
        if monitor_check_time:
            try:
                hour, minute, *_ = str(monitor_check_time).split(":")
                window_end_minutes = int(hour) * 60 + int(minute)
            except (TypeError, ValueError):
                window_end_minutes = T_RELAY_DAY2_MONITOR_END_MINUTE
        for row in rows:
            dt = cls._parse_datetime(row.get("tick_time") or row.get("event_time"))
            if dt is not None:
                local_dt = dt.astimezone(CHINA_TZ) if dt.tzinfo else dt
                minute_of_day = local_dt.hour * 60 + local_dt.minute
                if minute_of_day < T_RELAY_DAY2_MONITOR_START_MINUTE or minute_of_day > window_end_minutes:
                    continue
            amount = cls._decimal(row.get("amount"))
            if amount is None:
                continue
            included += 1
            side = str(row.get("side_code") or row.get("side_label") or "").strip().upper()
            if side in {"1", "B", "BUY", "BUYER", "买盘", "主动买入"}:
                buy_amount += amount
            elif side in {"2", "S", "SELL", "SELLER", "卖盘", "主动卖出"}:
                sell_amount += amount
        side = "UNKNOWN"
        amount: Decimal | None = None
        if buy_amount > 0 or sell_amount > 0:
            if buy_amount >= sell_amount:
                side = "ASK"
                amount = buy_amount
            else:
                side = "BID"
                amount = sell_amount
        return {
            "order_consumption_raw_label": "provider_native_trade_tick_side_code",
            "order_consumption_side": side,
            "order_consumption_amount": str(amount) if amount is not None else None,
            "aggressive_buy_sweep_amount": str(buy_amount) if buy_amount > 0 else None,
            "aggressive_sell_hit_bid_amount": str(sell_amount) if sell_amount > 0 else None,
            "p0_trade_tick_complete": bool(rows),
            "trade_tick_window_start_time": "09:30:00",
            "trade_tick_window_end_time": monitor_check_time or "10:30:00",
            "trade_tick_window_count": included,
        }

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @classmethod
    def _string_values(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            rows: list[str] = []
            for item in value:
                rows.extend(cls._string_values(item))
            return rows
        if isinstance(value, dict):
            rows: list[str] = []
            for item in value.values():
                rows.extend(cls._string_values(item))
            return rows
        return []

    @staticmethod
    def _first(source_rows: dict[str, dict[str, list[dict[str, Any]]]], table_name: str, symbol: str) -> dict[str, Any] | None:
        return ResearchPayloadAssembler._first_row(source_rows.get(table_name, {}).get(symbol, []))

    @staticmethod
    def _first_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        return rows[0] if rows else None

    @staticmethod
    def _latest_daily_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        return rows[-1] if rows else None

    @staticmethod
    def _value(row: dict[str, Any] | None, key: str) -> Any:
        return row.get(key) if row else None

    @staticmethod
    def _first_value(*rows: dict[str, Any] | None, keys: tuple[str, ...]) -> Any:
        for row in rows:
            if not row:
                continue
            for key in keys:
                value = row.get(key)
                if value not in (None, ""):
                    return value
        return None

    @classmethod
    def _sort_daily_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda row: str(row.get("trade_date") or row.get("trading_day") or row.get("calendar_date") or ""))

    @classmethod
    def _adjusted_daily_as_daily_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item.setdefault("open_price", row.get("adjusted_open") or row.get("open_price"))
            item.setdefault("high_price", row.get("adjusted_high") or row.get("high_price"))
            item.setdefault("low_price", row.get("adjusted_low") or row.get("low_price"))
            item.setdefault("close_price", row.get("adjusted_close") or row.get("close_price"))
            item.setdefault("pre_close_price", row.get("adjusted_pre_close") or row.get("pre_close_price"))
            item["daily_bar_source"] = "source.adjusted_daily_bar_v1"
            item.setdefault(
                "price_adjustment_mode",
                row.get("adjustment_mode") or row.get("adjustment") or row.get("adjustment_type") or "adjusted",
            )
            normalized.append(item)
        return cls._sort_daily_rows(normalized)

    @classmethod
    def _hot_batch_id(cls, paid: dict[str, Any] | None) -> str | None:
        if not paid:
            return None
        seed = {
            "source": "source.ths_paid_limit_up_probability_v1",
            "trade_date": cls._value(paid, "trade_date"),
            "build_batch_id": cls._value(paid, "build_batch_id"),
        }
        return str(int(stable_hash(seed)[:15], 16))

    @classmethod
    def _hot_candidate_id(cls, paid: dict[str, Any] | None, symbol: str) -> str | None:
        if not paid:
            return None
        seed = {
            "batch_id": cls._hot_batch_id(paid),
            "symbol": symbol,
            "trade_date": cls._value(paid, "trade_date"),
        }
        return str(int(stable_hash(seed)[:15], 16))

    @staticmethod
    def _infer_trade_date(source_rows: dict[str, dict[str, list[dict[str, Any]]]], symbol: str) -> str | None:
        for table_rows in source_rows.values():
            rows = table_rows.get(symbol, [])
            if rows:
                return rows[0].get("trade_date") or rows[0].get("trading_day") or rows[0].get("calendar_date")
        return None

    @staticmethod
    def _gap_slug(table_name: str) -> str:
        return table_name.replace(".", "_").replace("source_", "").replace("_v1", "")
