from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class ResearchRepositoryError(RuntimeError):
    pass


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def stable_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


JSONB_VALUE_COLUMNS = {
    "first_outcome_summary",
    "missing_symbols",
    "operator_notes",
    "recommended_correction",
    "release_gate_reason",
    "secondary_distortion_factors",
    "tracking_reason_codes",
    "used_by_models",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


HOT_READINESS_WEIGHT_TOTAL = 100

HOT_READINESS_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {
        "code": "candidate_identity_tradeability",
        "label": "候选与可交易",
        "priority": "P0",
        "weight": 12,
        "gap_code": "source_gap:candidate_identity_tradeability_missing",
        "source_tables": ("decision_hot.hot_decision_case_v1", "source.stock_master_v1", "source.trade_status_v1"),
        "handling": "缺身份或可交易状态时阻断，不用名称或样例补齐。",
    },
    {
        "code": "ths_paid_probability",
        "label": "同花顺付费概率",
        "priority": "P0",
        "weight": 22,
        "gap_code": "source_gap:ths_paid_probability_missing",
        "source_tables": ("source.ths_paid_limit_up_probability_v1",),
        "handling": "教师先验缺失时等待或放弃批次，禁止补 0。",
    },
    {
        "code": "trade_calendar_deadline",
        "label": "交易日历与窗口",
        "priority": "P0",
        "weight": 6,
        "gap_code": "source_gap:trade_calendar_deadline_missing",
        "source_tables": ("source.trade_calendar_v1",),
        "handling": "用于 deadline、T+N 和补产窗口。",
    },
    {
        "code": "daily_limit_event",
        "label": "日线与涨跌停",
        "priority": "P0",
        "weight": 12,
        "gap_code": "source_gap:daily_limit_event_missing",
        "source_tables": ("source.daily_bar_v1", "source.limit_price_v1", "source.limit_event_v1"),
        "handling": "缺日线、涨跌停价或事件时保留缺口。",
    },
    {
        "code": "auction_confirmation",
        "label": "竞价确认",
        "priority": "P0",
        "weight": 10,
        "gap_code": "source_gap:auction_confirmation",
        "source_tables": ("source.auction_snapshot_v1",),
        "handling": "竞价事实必须带时间线，缺失不推断。",
    },
    {
        "code": "open_5m_reference_path",
        "label": "开盘路径与基准价",
        "priority": "P0",
        "weight": 8,
        "gap_code": "source_gap:open_5m_reference_path_missing",
        "source_tables": ("source.minute_bar_v1", "source.realtime_quote_v1", "decision_hot.hot_buy_point_v1"),
        "handling": "开盘 5 分钟与评估基准缺失时不生成买点。",
    },
    {
        "code": "source_governance_preflight",
        "label": "source 治理门禁",
        "priority": "P0",
        "weight": 5,
        "gap_code": "source_gap:source_preflight_not_passed",
        "source_tables": ("governance.source_lineage_v1", "/source/release/preflight"),
        "handling": "lineage、available_at 或 preflight 未过时阻断。",
    },
    {
        "code": "moneyflow_context",
        "label": "资金上下文",
        "priority": "P1",
        "weight": 7,
        "gap_code": "source_gap:stock_moneyflow_rank",
        "source_tables": ("source.stock_moneyflow_daily_v1", "source.moneyflow_stock_snapshot_v1"),
        "handling": "缺资金时降级展示，不补资金值。",
    },
    {
        "code": "market_regime_context",
        "label": "市场环境",
        "priority": "P1",
        "weight": 5,
        "gap_code": "source_gap:market_regime_context",
        "source_tables": ("source.market_regime_snapshot_v1", "source.index_daily_bar_v1"),
        "handling": "缺市场环境时降级，不改变 P0 阻断语义。",
    },
    {
        "code": "board_theme_context",
        "label": "题材板块",
        "priority": "P1",
        "weight": 4,
        "gap_code": "source_gap:board_theme_context",
        "source_tables": ("source.stock_board_membership_v1", "source.board_daily_bar_v1"),
        "handling": "缺题材时只降级解释，不编造板块。",
    },
    {
        "code": "inspection_context",
        "label": "巡检上下文",
        "priority": "P1",
        "weight": 2,
        "gap_code": "source_gap:inspection_context",
        "source_tables": ("data-inspector-service",),
        "handling": "巡检缺口必须继续可见。",
    },
    {
        "code": "news_event_context",
        "label": "新闻事件",
        "priority": "P2",
        "weight": 4,
        "gap_code": "source_gap:news_event_context",
        "source_tables": ("source.event_news_v1",),
        "handling": "research-only 上下文，缺失不变成硬事实。",
    },
    {
        "code": "outcome_evolution_context",
        "label": "后验验证",
        "priority": "P2",
        "weight": 3,
        "gap_code": "source_gap:outcome_evolution_context",
        "source_tables": ("decision_hot.hot_outcome_label_v1", "decision_hot.hot_evolution_sample_v1"),
        "handling": "未成熟时保持待验证，不显示成功。",
    },
)


class ResearchPayloadRepository:
    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url
        self._table_exists_cache: dict[str, bool] = {}
        self._table_columns_cache: dict[str, set[str]] = {}

    def ready(self) -> dict[str, Any]:
        if not self.database_url:
            return {"status": "degraded", "database_url_configured": False}
        try:
            source_ready = self.table_exists("source.daily_bar_v1")
            audit_ready = self.table_exists("governance.research_model_payload_assembly_audit_v1")
            execution_audit_ready = self.table_exists("governance.research_model_execution_audit_v1")
            return {
                "status": "ready" if source_ready and audit_ready and execution_audit_ready else "not_ready",
                "database_url_configured": True,
                "source_daily_bar_ready": source_ready,
                "assembly_audit_ready": audit_ready,
                "execution_audit_ready": execution_audit_ready,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "not_ready", "database_url_configured": True, "error": str(exc)}

    def table_exists(self, table_name: str) -> bool:
        if table_name in self._table_exists_cache:
            return self._table_exists_cache[table_name]
        schema, table = self._split_table(table_name)
        row = self._fetch_one(
            """
            select exists (
                select 1
                from information_schema.tables
                where table_schema = %(schema)s and table_name = %(table)s
            ) as exists
            """,
            {"schema": schema, "table": table},
        )
        exists = bool(row and row["exists"])
        self._table_exists_cache[table_name] = exists
        return exists

    def table_columns(self, table_name: str) -> set[str]:
        if table_name in self._table_columns_cache:
            return self._table_columns_cache[table_name]
        schema, table = self._split_table(table_name)
        rows = self._fetch_all(
            """
            select column_name
            from information_schema.columns
            where table_schema = %(schema)s and table_name = %(table)s
            """,
            {"schema": schema, "table": table},
        )
        columns = {str(row["column_name"]) for row in rows}
        self._table_columns_cache[table_name] = columns
        return columns

    def fetch_source_rows(
        self,
        table_name: str,
        *,
        symbol: str | None,
        trade_date: date,
        limit: int,
        before_or_on: bool = False,
    ) -> list[dict[str, Any]]:
        schema, table = self._split_table(table_name)
        if schema != "source":
            raise ResearchRepositoryError("source fetch only allows source.* tables")
        if not self.table_exists(table_name):
            return []
        columns = self.table_columns(table_name)
        clauses: list[sql.Composed] = []
        params: dict[str, Any] = {"trade_date": trade_date, "limit": limit}
        if symbol and "symbol" in columns:
            clauses.append(sql.SQL("symbol = %(symbol)s"))
            params["symbol"] = symbol
        date_operator = sql.SQL("<=") if before_or_on else sql.SQL("=")
        if "trade_date" in columns:
            clauses.append(sql.SQL("trade_date {} %(trade_date)s").format(date_operator))
        elif "trading_day" in columns:
            clauses.append(sql.SQL("trading_day {} %(trade_date)s").format(date_operator))
        elif "calendar_date" in columns:
            clauses.append(sql.SQL("calendar_date {} %(trade_date)s").format(date_operator))
        elif "bar_time" in columns:
            clauses.append(sql.SQL("bar_time::date {} %(trade_date)s").format(date_operator))
        elif "tick_time" in columns:
            clauses.append(sql.SQL("tick_time::date {} %(trade_date)s").format(date_operator))
        elif table_name != "source.stock_master_v1":
            clauses.append(sql.SQL("captured_at::date <= %(trade_date)s"))
        order_column = self._best_order_column(columns)
        query = sql.SQL("select * from {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
        if clauses:
            query += sql.SQL(" where ") + sql.SQL(" and ").join(clauses)
        query += sql.SQL(" order by {} desc nulls last limit %(limit)s").format(sql.Identifier(order_column))
        return self._fetch_all_sql(query, params)

    def fetch_hot_score_candidate_symbols(self, *, trade_date: date, limit: int = 1000) -> list[str]:
        if not self.table_exists("source.ths_paid_limit_up_probability_v1"):
            return []
        rows = self._fetch_all(
            """
            select symbol
            from source.ths_paid_limit_up_probability_v1
            where trade_date = %(trade_date)s
            order by paid_limit_up_probability desc nulls last, updated_at desc nulls last, symbol
            limit %(limit)s
            """,
            {"trade_date": trade_date, "limit": max(1, min(int(limit), 2000))},
        )
        return [str(row["symbol"]).upper() for row in rows if row.get("symbol")]

    def fetch_hot_stage_candidate_symbols(self, *, trade_date: date, task_code: str, limit: int = 1000) -> list[str]:
        if task_code == "hot.score.auction_confirmed":
            return self.fetch_hot_score_candidate_symbols(trade_date=trade_date, limit=limit)
        if not self.table_exists("decision_hot.hot_decision_case_v1") or not self.table_exists("decision_hot.hot_score_fact_v1"):
            return []
        rows = self._fetch_all(
            """
            select c.symbol
            from (
                select *
                from (
                    select
                        base_case.*,
                        row_number() over (
                            partition by base_case.symbol, base_case.trade_date
                            order by
                                exists (
                                    select 1
                                    from decision_hot.hot_score_fact_v1 score
                                    where score.hot_case_id = base_case.hot_case_id
                                ) desc,
                                base_case.updated_at desc nulls last,
                                base_case.created_at desc nulls last
                        ) as current_case_rank
                    from decision_hot.hot_decision_case_v1 base_case
                ) ranked_case
                where ranked_case.current_case_rank = 1
            ) c
            join lateral (
                select *
                from decision_hot.hot_score_fact_v1 score
                where score.hot_case_id = c.hot_case_id
                order by score.created_at desc nulls last, score.score_id desc
                limit 1
            ) s on true
            where c.trade_date = %(trade_date)s
            order by
                coalesce(
                    s.official_hot_score,
                    s.open_5m_confirmed_score,
                    s.auction_confirmed_score,
                    s.pre_auction_score,
                    c.p_limit_up_calibrated,
                    c.p_limit_up_raw
                ) desc nulls last,
                c.updated_at desc nulls last,
                c.symbol
            limit %(limit)s
            """,
            {"trade_date": trade_date, "limit": max(1, min(int(limit), 2000))},
        )
        seen: set[str] = set()
        symbols: list[str] = []
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            if symbol and symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
        return symbols

    def fetch_upstream_rows(self, table_name: str, *, symbol: str | None, trade_date: date, limit: int = 20) -> list[dict[str, Any]]:
        schema, table = self._split_table(table_name)
        if schema.startswith("raw") or schema == "raw":
            raise ResearchRepositoryError("research-service must not read raw tables")
        if not self.table_exists(table_name):
            return []
        columns = self.table_columns(table_name)
        clauses: list[sql.Composed] = []
        params: dict[str, Any] = {"trade_date": trade_date, "limit": limit}
        symbol_column = "symbol" if "symbol" in columns else "canonical_symbol" if "canonical_symbol" in columns else None
        if symbol and symbol_column:
            clauses.append(sql.SQL("{} = %(symbol)s").format(sql.Identifier(symbol_column)))
            params["symbol"] = symbol
        date_column = self._best_date_column(columns)
        if date_column:
            if date_column.endswith("_at") or date_column == "created_at":
                clauses.append(sql.SQL("{}::date <= %(trade_date)s").format(sql.Identifier(date_column)))
            else:
                clauses.append(sql.SQL("{} = %(trade_date)s").format(sql.Identifier(date_column)))
        order_column = self._best_order_column(columns)
        query = sql.SQL("select * from {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
        if clauses:
            query += sql.SQL(" where ") + sql.SQL(" and ").join(clauses)
        query += sql.SQL(" order by {} desc nulls last limit %(limit)s").format(sql.Identifier(order_column))
        return self._fetch_all_sql(query, params)

    def fetch_hot_case_upstream_rows(self, table_name: str, *, symbol: str | None, trade_date: date, limit: int = 20) -> list[dict[str, Any]]:
        schema, table = self._split_table(table_name)
        allowed = {
            ("decision_hot", "hot_decision_case_v1"),
            ("decision_hot", "hot_score_fact_v1"),
            ("decision_hot", "hot_evidence_snapshot_v1"),
            ("decision_hot", "hot_release_gate_audit_v1"),
            ("decision_hot", "hot_signal_fact_v1"),
        }
        if (schema, table) not in allowed:
            return self.fetch_upstream_rows(table_name, symbol=symbol, trade_date=trade_date, limit=limit)
        if not symbol:
            return []
        if not self.table_exists(table_name) or not self.table_exists("decision_hot.hot_decision_case_v1"):
            return []
        if table_name == "decision_hot.hot_decision_case_v1":
            return self._fetch_all(
                """
                select *
                from (
                    select
                        base_case.*,
                        row_number() over (
                            partition by base_case.symbol, base_case.trade_date
                            order by
                                exists (
                                    select 1
                                    from decision_hot.hot_score_fact_v1 score
                                    where score.hot_case_id = base_case.hot_case_id
                                ) desc,
                                base_case.updated_at desc nulls last,
                                base_case.created_at desc nulls last
                        ) as current_case_rank
                    from decision_hot.hot_decision_case_v1 base_case
                    where base_case.symbol = %(symbol)s
                      and base_case.trade_date = %(trade_date)s
                ) ranked_case
                where ranked_case.current_case_rank = 1
                limit %(limit)s
                """,
                {"symbol": symbol, "trade_date": trade_date, "limit": limit},
            )
        order_column = self._best_order_column(self.table_columns(table_name))
        query = sql.SQL(
            """
            select upstream.*
            from {}.{} upstream
            join decision_hot.hot_decision_case_v1 cases
              on cases.hot_case_id = upstream.hot_case_id
            where cases.symbol = %(symbol)s
              and cases.trade_date = %(trade_date)s
            order by upstream.{} desc nulls last
            limit %(limit)s
            """
        ).format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(order_column))
        return self._fetch_all_sql(query, {"symbol": symbol, "trade_date": trade_date, "limit": limit})

    def fetch_hot_release_upstream_rows(self, table_name: str, *, symbol: str | None, trade_date: date, limit: int = 20) -> list[dict[str, Any]]:
        return self.fetch_hot_case_upstream_rows(table_name, symbol=symbol, trade_date=trade_date, limit=limit)

    def fetch_hot_model_list(self, *, limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        required_tables = {
            "decision_hot.hot_decision_case_v1",
            "decision_hot.hot_score_fact_v1",
            "decision_hot.hot_release_gate_audit_v1",
            "decision_hot.hot_signal_fact_v1",
            "decision_hot.hot_buy_point_v1",
            "source.stock_master_v1",
            "source.daily_bar_v1",
            "source.ths_paid_limit_up_probability_v1",
        }
        missing_tables = sorted(table for table in required_tables if not self.table_exists(table))
        if "decision_hot.hot_decision_case_v1" in missing_tables:
            return {
                "contract_kind": "research_hot_model_list_v1",
                "model_code": "hot_candidates",
                "read_only": True,
                "readiness_contract": "hot_model_data_readiness_v1",
                "readiness_weight_total": HOT_READINESS_WEIGHT_TOTAL,
                "readiness_dimensions": [dict(dimension) for dimension in HOT_READINESS_DIMENSIONS],
                "readiness_summary": _hot_readiness_summary([]),
                "items": [],
                "item_count": 0,
                "gap_codes": ["source_gap:hot_decision_list_not_materialized"],
                "missing_tables": missing_tables,
            }
        if missing_tables:
            return {
                "contract_kind": "research_hot_model_list_v1",
                "model_code": "hot_candidates",
                "read_only": True,
                "readiness_contract": "hot_model_data_readiness_v1",
                "readiness_weight_total": HOT_READINESS_WEIGHT_TOTAL,
                "readiness_dimensions": [dict(dimension) for dimension in HOT_READINESS_DIMENSIONS],
                "readiness_summary": _hot_readiness_summary([]),
                "items": [],
                "item_count": 0,
                "gap_codes": [f"source_gap:{table.replace('.', '_')}_missing" for table in missing_tables],
                "missing_tables": missing_tables,
            }

        rows = self._fetch_all(
            """
            select
                c.hot_case_id,
                c.hot_cycle_id,
                c.symbol,
                coalesce(c.stock_name, sm.stock_name) as stock_name,
                c.trade_date,
                c.decision_time,
                c.lifecycle_stage_at_decision,
                c.board_count_at_decision,
                c.p_limit_up_raw,
                c.p_limit_up_calibrated,
                c.case_status,
                c.created_at as case_created_at,
                c.updated_at as case_updated_at,
                s.score_id,
                s.model_version as score_model_version,
                s.score_stage,
                s.pre_auction_score,
                s.auction_confirmed_score,
                s.open_5m_confirmed_score,
                s.official_hot_score,
                s.scoring_state,
                s.recommendation_eligibility,
                s.main_positive_factors_json,
                s.main_negative_factors_json,
                s.hard_block_reasons_json,
                s.warning_reasons_json as score_warning_reasons_json,
                s.created_at as score_created_at,
                g.release_gate_id,
                g.gate_status,
                g.official_signal_allowed,
                g.signal_stage as release_signal_stage,
                g.block_reasons_json as release_block_reasons_json,
                g.warning_reasons_json as release_warning_reasons_json,
                g.required_evidence_status,
                g.gate_time,
                g.created_at as release_created_at,
                sig.hot_signal_id,
                sig.signal_date,
                sig.selected_at,
                sig.model_score as signal_model_score,
                sig.signal_stage,
                sig.is_official_signal,
                sig.is_research_only,
                sig.release_gate_status,
                sig.release_gate_reason,
                sig.updated_at as signal_updated_at,
                buy.buy_point_id,
                buy.reference_entry_price,
                buy.entry_price_low,
                buy.entry_price_high,
                buy.target_price,
                buy.invalidation_price,
                buy.risk_reward_ratio,
                buy.buy_point_status,
                buy.block_reason as buy_point_block_reason,
                buy.calculated_at as buy_point_calculated_at,
                buy.data_as_of as buy_point_data_as_of,
                buy.created_at as buy_point_created_at,
                daily.close_price as current_price,
                daily.pct_chg as latest_pct_chg,
                daily.available_at as daily_available_at,
                paid.paid_limit_up_probability,
                paid.available_at as paid_probability_available_at,
                greatest(
                    c.updated_at,
                    coalesce(s.created_at, c.updated_at),
                    coalesce(g.created_at, c.updated_at),
                    coalesce(sig.updated_at, c.updated_at),
                    coalesce(buy.created_at, c.updated_at),
                    coalesce(daily.available_at, c.updated_at),
                    coalesce(paid.updated_at, paid.available_at, c.updated_at)
                ) as latest_snapshot_time,
                coalesce(
                    sig.model_score,
                    s.official_hot_score,
                    s.open_5m_confirmed_score,
                    s.auction_confirmed_score,
                    s.pre_auction_score
                ) as model_score
            from (
                select *
                from (
                    select
                        base_case.*,
                        row_number() over (
                            partition by base_case.symbol, base_case.trade_date
                            order by
                                exists (
                                    select 1
                                    from decision_hot.hot_score_fact_v1 score
                                    where score.hot_case_id = base_case.hot_case_id
                                ) desc,
                                base_case.updated_at desc nulls last,
                                base_case.created_at desc nulls last
                        ) as current_case_rank
                    from decision_hot.hot_decision_case_v1 base_case
                ) ranked_case
                where ranked_case.current_case_rank = 1
            ) c
            left join source.stock_master_v1 sm
              on sm.symbol = c.symbol
            left join lateral (
                select *
                from decision_hot.hot_score_fact_v1 score
                where score.hot_case_id = c.hot_case_id
                order by score.created_at desc nulls last, score.score_id desc
                limit 1
            ) s on true
            left join lateral (
                select *
                from decision_hot.hot_release_gate_audit_v1 gate
                where gate.hot_case_id = c.hot_case_id
                order by gate.created_at desc nulls last, gate.release_gate_id desc
                limit 1
            ) g on true
            left join lateral (
                select *
                from decision_hot.hot_signal_fact_v1 signal
                where signal.hot_case_id = c.hot_case_id
                order by signal.updated_at desc nulls last, signal.created_at desc nulls last
                limit 1
            ) sig on true
            left join lateral (
                select *
                from decision_hot.hot_buy_point_v1 buy_point
                where buy_point.hot_case_id = c.hot_case_id
                order by buy_point.is_frozen_reference desc, buy_point.created_at desc nulls last
                limit 1
            ) buy on true
            left join lateral (
                select *
                from source.daily_bar_v1 bar
                where bar.symbol = c.symbol
                  and (bar.trade_date = c.trade_date or bar.trading_day = c.trade_date)
                order by bar.available_at desc nulls last
                limit 1
            ) daily on true
            left join source.ths_paid_limit_up_probability_v1 paid
              on paid.symbol = c.symbol
             and paid.trade_date = c.trade_date
            order by
                coalesce(
                    sig.model_score,
                    s.official_hot_score,
                    s.open_5m_confirmed_score,
                    s.auction_confirmed_score,
                    s.pre_auction_score
                ) desc nulls last,
                c.trade_date desc nulls last,
                c.updated_at desc
            limit %(limit)s
            """,
            {"limit": limit},
        )
        support_by_case = {
            str(row["hot_case_id"]): self._hot_readiness_support(row)
            for row in rows
            if row.get("hot_case_id")
        }
        items = [_hot_model_list_item(row, readiness_support=support_by_case.get(str(row.get("hot_case_id")))) for row in rows]
        return {
            "contract_kind": "research_hot_model_list_v1",
            "model_code": "hot_candidates",
            "read_only": True,
            "readiness_contract": "hot_model_data_readiness_v1",
            "readiness_weight_total": HOT_READINESS_WEIGHT_TOTAL,
            "readiness_dimensions": [dict(dimension) for dimension in HOT_READINESS_DIMENSIONS],
            "readiness_summary": _hot_readiness_summary(items),
            "items": items,
            "item_count": len(items),
            "gap_codes": sorted({gap for item in items for gap in item.get("source_gaps", [])}),
        }

    def _hot_readiness_support(self, row: dict[str, Any]) -> dict[str, bool]:
        symbol = str(row.get("symbol") or "")
        trade_date = _date_from_value(row.get("trade_date"))
        if not symbol or trade_date is None:
            return {}
        return {
            "trade_status": self._has_source_fact("source.trade_status_v1", symbol=symbol, trade_date=trade_date),
            "trade_calendar": self._has_source_fact("source.trade_calendar_v1", symbol=None, trade_date=trade_date),
            "limit_price": self._has_source_fact("source.limit_price_v1", symbol=symbol, trade_date=trade_date),
            "limit_event": self._has_source_fact("source.limit_event_v1", symbol=symbol, trade_date=trade_date),
            "auction": self._has_source_fact("source.auction_snapshot_v1", symbol=symbol, trade_date=trade_date),
            "minute_bar": self._has_source_fact("source.minute_bar_v1", symbol=symbol, trade_date=trade_date),
            "realtime_quote": self._has_source_fact("source.realtime_quote_v1", symbol=symbol, trade_date=trade_date),
            "lineage": self._has_lineage_fact(symbol=symbol, trade_date=trade_date),
            "moneyflow": self._has_any_source_fact(
                ("source.stock_moneyflow_daily_v1", "source.moneyflow_stock_snapshot_v1"),
                symbol=symbol,
                trade_date=trade_date,
            ),
            "market_regime": self._has_any_source_fact(
                ("source.market_regime_snapshot_v1", "source.index_daily_bar_v1"),
                symbol=None,
                trade_date=trade_date,
            ),
            "board_theme": self._has_any_source_fact(
                ("source.stock_board_membership_v1", "source.board_daily_bar_v1"),
                symbol=symbol,
                trade_date=trade_date,
                before_or_on=True,
            ),
            "news_event": self._has_source_fact("source.event_news_v1", symbol=symbol, trade_date=trade_date, before_or_on=True),
            "outcome": self._has_hot_case_fact("decision_hot.hot_outcome_label_v1", hot_case_id=str(row.get("hot_case_id"))),
            "evolution": self._has_hot_case_fact("decision_hot.hot_evolution_sample_v1", hot_case_id=str(row.get("hot_case_id"))),
        }

    def _has_any_source_fact(
        self,
        table_names: tuple[str, ...],
        *,
        symbol: str | None,
        trade_date: date,
        before_or_on: bool = False,
    ) -> bool:
        return any(self._has_source_fact(table, symbol=symbol, trade_date=trade_date, before_or_on=before_or_on) for table in table_names)

    def _has_source_fact(
        self,
        table_name: str,
        *,
        symbol: str | None,
        trade_date: date,
        before_or_on: bool = False,
    ) -> bool:
        if not self.table_exists(table_name):
            return False
        schema, table = self._split_table(table_name)
        columns = self.table_columns(table_name)
        clauses: list[sql.Composed] = []
        params: dict[str, Any] = {"trade_date": trade_date}
        if symbol and "symbol" in columns:
            clauses.append(sql.SQL("symbol = %(symbol)s"))
            params["symbol"] = symbol
        date_operator = sql.SQL("<=") if before_or_on else sql.SQL("=")
        if "trade_date" in columns:
            clauses.append(sql.SQL("trade_date {} %(trade_date)s").format(date_operator))
        elif "trading_day" in columns:
            clauses.append(sql.SQL("trading_day {} %(trade_date)s").format(date_operator))
        elif "calendar_date" in columns:
            clauses.append(sql.SQL("calendar_date {} %(trade_date)s").format(date_operator))
        elif "bar_time" in columns:
            clauses.append(sql.SQL("bar_time::date {} %(trade_date)s").format(date_operator))
        elif "event_time" in columns:
            clauses.append(sql.SQL("event_time::date {} %(trade_date)s").format(date_operator))
        elif "published_at" in columns:
            clauses.append(sql.SQL("published_at::date {} %(trade_date)s").format(sql.SQL("<=")))
        elif "as_of_time" in columns:
            clauses.append(sql.SQL("as_of_time::date {} %(trade_date)s").format(date_operator))
        if "source_quality_status" in columns:
            clauses.append(sql.SQL("coalesce(source_quality_status, '') in ('usable', 'research_only', 'source_visible', 'ready')"))
        elif "quality_status" in columns:
            clauses.append(sql.SQL("coalesce(quality_status, '') in ('usable', 'research_only', 'source_visible', 'ready')"))
        query = sql.SQL("select 1 from {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
        if clauses:
            query += sql.SQL(" where ") + sql.SQL(" and ").join(clauses)
        query += sql.SQL(" limit 1")
        return bool(self._fetch_all_sql(query, params))

    def _has_lineage_fact(self, *, symbol: str, trade_date: date) -> bool:
        if not self.table_exists("governance.source_lineage_v1"):
            return False
        columns = self.table_columns("governance.source_lineage_v1")
        if "source_pk" not in columns:
            return False
        clauses: list[sql.Composed] = [sql.SQL("source_pk::text like %(symbol_like)s")]
        params: dict[str, Any] = {"symbol_like": f"%{symbol}%"}
        if "build_created_at" in columns:
            clauses.append(sql.SQL("build_created_at::date <= %(trade_date)s"))
            params["trade_date"] = trade_date
        elif "created_at" in columns:
            clauses.append(sql.SQL("created_at::date <= %(trade_date)s"))
            params["trade_date"] = trade_date
        query = sql.SQL("select 1 from governance.source_lineage_v1 where ") + sql.SQL(" and ").join(clauses) + sql.SQL(" limit 1")
        return bool(self._fetch_all_sql(query, params))

    def _has_hot_case_fact(self, table_name: str, *, hot_case_id: str | None) -> bool:
        if not hot_case_id or not self.table_exists(table_name):
            return False
        columns = self.table_columns(table_name)
        if "hot_case_id" not in columns:
            return False
        schema, table = self._split_table(table_name)
        query = sql.SQL("select 1 from {}.{} where hot_case_id = %(hot_case_id)s limit 1").format(sql.Identifier(schema), sql.Identifier(table))
        return bool(self._fetch_all_sql(query, {"hot_case_id": hot_case_id}))

    def previous_trading_day(self, trade_date: date) -> date | None:
        if not self.table_exists("source.trade_calendar_v1"):
            return None
        columns = self.table_columns("source.trade_calendar_v1")
        if "calendar_date" not in columns or "is_trading_day" not in columns:
            return None
        row = self._fetch_one(
            """
            select calendar_date
            from source.trade_calendar_v1
            where calendar_date < %(trade_date)s
              and is_trading_day = true
            order by calendar_date desc
            limit 1
            """,
            {"trade_date": trade_date},
        )
        return row["calendar_date"] if row else None

    def persist_assembly_audit(
        self,
        *,
        assembly_id: str,
        task_code: str,
        owner_service: str,
        model_code: str,
        model_phase: str | None,
        symbol: str | None,
        trade_date: str,
        status: str,
        gap_codes: list[str],
        source_refs: list[dict[str, Any]],
        upstream_refs: list[dict[str, Any]],
        payload_hash: str,
        payload: dict[str, Any],
    ) -> bool:
        if not self.database_url or not self.table_exists("governance.research_model_payload_assembly_audit_v1"):
            return False
        with self._connect() as conn:
            conn.execute(
                """
                insert into governance.research_model_payload_assembly_audit_v1 (
                    assembly_id, task_code, owner_service, model_code, model_phase,
                    symbol, trade_date, payload_assembly_status, gap_codes,
                    source_refs, upstream_refs, payload_hash, payload
                ) values (
                    %(assembly_id)s, %(task_code)s, %(owner_service)s, %(model_code)s,
                    %(model_phase)s, %(symbol)s, %(trade_date)s, %(status)s,
                    %(gap_codes)s, %(source_refs)s, %(upstream_refs)s, %(payload_hash)s,
                    %(payload)s
                )
                on conflict (assembly_id) do nothing
                """,
                {
                    "assembly_id": assembly_id,
                    "task_code": task_code,
                    "owner_service": owner_service,
                    "model_code": model_code,
                    "model_phase": model_phase,
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "status": status,
                    "gap_codes": Jsonb(gap_codes),
                    "source_refs": Jsonb(source_refs),
                    "upstream_refs": Jsonb(upstream_refs),
                    "payload_hash": payload_hash,
                    "payload": Jsonb(payload),
                },
            )
            conn.commit()
        return True

    def insert_row(self, table_name: str, values: dict[str, Any]) -> bool:
        if not self.database_url or not self.table_exists(table_name):
            return False
        schema, table = self._split_table(table_name)
        columns = self.table_columns(table_name)
        filtered = {key: values[key] for key in values if key in columns}
        if not filtered:
            return False
        identifiers = [sql.Identifier(column) for column in filtered]
        placeholders = [sql.Placeholder(column) for column in filtered]
        query = (
            sql.SQL("insert into {}.{} ({}) values ({}) on conflict do nothing")
            .format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.SQL(", ").join(identifiers),
                sql.SQL(", ").join(placeholders),
            )
        )
        params = {key: self._bind_value(key, value) for key, value in filtered.items()}
        with self._connect() as conn:
            conn.execute(query, params)
            conn.commit()
        return True

    def persist_execution_audit(
        self,
        *,
        execution_id: str,
        assembly_id: str | None,
        task_code: str,
        owner_service: str,
        model_code: str,
        model_phase: str | None,
        symbol: str | None,
        trade_date: str,
        run_id: str,
        payload_hash: str | None,
        owner_endpoint: str | None,
        owner_status_code: int | None,
        execution_status: str,
        accepted: bool,
        dispatch_allowed: bool,
        owner_called: bool,
        materialization_attempted: bool,
        gap_codes: list[str],
        error_code: str | None,
        error_message: str | None,
        owner_request: dict[str, Any] | None,
        owner_response: dict[str, Any] | None,
        materialized_counts: dict[str, Any],
    ) -> bool:
        if not self.database_url or not self.table_exists("governance.research_model_execution_audit_v1"):
            return False
        with self._connect() as conn:
            conn.execute(
                """
                insert into governance.research_model_execution_audit_v1 (
                    execution_id, assembly_id, task_code, owner_service, model_code, model_phase,
                    symbol, trade_date, run_id, payload_hash, owner_endpoint, owner_status_code,
                    execution_status, accepted, dispatch_allowed, owner_called, materialization_attempted,
                    gap_codes, error_code, error_message, owner_request, owner_response, materialized_counts
                ) values (
                    %(execution_id)s, %(assembly_id)s, %(task_code)s, %(owner_service)s,
                    %(model_code)s, %(model_phase)s, %(symbol)s, %(trade_date)s, %(run_id)s,
                    %(payload_hash)s, %(owner_endpoint)s, %(owner_status_code)s, %(execution_status)s,
                    %(accepted)s, %(dispatch_allowed)s, %(owner_called)s, %(materialization_attempted)s,
                    %(gap_codes)s, %(error_code)s, %(error_message)s, %(owner_request)s,
                    %(owner_response)s, %(materialized_counts)s
                )
                on conflict (execution_id) do nothing
                """,
                {
                    "execution_id": execution_id,
                    "assembly_id": assembly_id,
                    "task_code": task_code,
                    "owner_service": owner_service,
                    "model_code": model_code,
                    "model_phase": model_phase,
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "run_id": run_id,
                    "payload_hash": payload_hash,
                    "owner_endpoint": owner_endpoint,
                    "owner_status_code": owner_status_code,
                    "execution_status": execution_status,
                    "accepted": accepted,
                    "dispatch_allowed": dispatch_allowed,
                    "owner_called": owner_called,
                    "materialization_attempted": materialization_attempted,
                    "gap_codes": Jsonb(gap_codes),
                    "error_code": error_code,
                    "error_message": error_message,
                    "owner_request": Jsonb(owner_request or {}),
                    "owner_response": Jsonb(owner_response or {}),
                    "materialized_counts": Jsonb(materialized_counts),
                },
            )
            conn.commit()
        return True

    def _connect(self) -> psycopg.Connection:
        if not self.database_url:
            raise ResearchRepositoryError("database url is not configured")
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _fetch_one(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return jsonable(row) if row else None

    def _fetch_all(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [jsonable(row) for row in rows]

    def _fetch_all_sql(self, query: sql.Composable, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [jsonable(row) for row in rows]

    @staticmethod
    def _split_table(table_name: str) -> tuple[str, str]:
        parts = table_name.split(".")
        if len(parts) != 2 or not all(part.replace("_", "").isalnum() for part in parts):
            raise ResearchRepositoryError(f"invalid table name: {table_name}")
        return parts[0], parts[1]

    @staticmethod
    def _best_date_column(columns: set[str]) -> str | None:
        for name in ("trade_date", "signal_date", "day2_trade_date", "day3_trade_date", "published_at", "created_at"):
            if name in columns:
                return name
        return None

    @staticmethod
    def _best_order_column(columns: set[str]) -> str:
        for name in ("available_at", "event_time", "bar_time", "tick_time", "published_at", "captured_at", "created_at", "trade_date"):
            if name in columns:
                return name
        return sorted(columns)[0] if columns else "1"

    @staticmethod
    def _bind_value(column: str, value: Any) -> Any:
        if value is not None and column in JSONB_VALUE_COLUMNS:
            return Jsonb(jsonable(value))
        if isinstance(value, (dict, list, tuple, set)) and (
            column.endswith("_json")
            or column.endswith("_jsonb")
            or column.endswith("_payload")
            or column in {"payload", "owner_request", "owner_response", "materialized_counts"}
        ):
            return Jsonb(jsonable(value))
        return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _score_label(row: dict[str, Any]) -> str | None:
    if row.get("signal_model_score") is not None:
        return "官方信号分"
    if row.get("official_hot_score") is not None:
        return "官方分"
    if row.get("open_5m_confirmed_score") is not None:
        return "开盘确认"
    if row.get("auction_confirmed_score") is not None:
        return "竞价确认"
    if row.get("pre_auction_score") is not None:
        return "盘前预估"
    return None


def _date_from_value(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _has_any_gap(source_gaps: list[str], gap_codes: tuple[str, ...]) -> bool:
    return any(gap in source_gaps for gap in gap_codes)


def _readiness_dimension_ok(code: str, row: dict[str, Any], source_gaps: list[str], support: dict[str, bool]) -> bool:
    if code == "candidate_identity_tradeability":
        return bool(row.get("hot_case_id") and row.get("symbol") and row.get("stock_name")) and support.get("trade_status", False)
    if code == "ths_paid_probability":
        return _first_non_empty(row.get("p_limit_up_calibrated"), row.get("p_limit_up_raw"), row.get("paid_limit_up_probability")) is not None
    if code == "trade_calendar_deadline":
        return support.get("trade_calendar", False)
    if code == "daily_limit_event":
        return bool(row.get("current_price") is not None and support.get("limit_price") and support.get("limit_event"))
    if code == "auction_confirmation":
        return bool(row.get("auction_confirmed_score") is not None or support.get("auction"))
    if code == "open_5m_reference_path":
        return bool(row.get("open_5m_confirmed_score") is not None or (_has_value(row.get("reference_entry_price")) and (support.get("minute_bar") or support.get("realtime_quote"))))
    if code == "source_governance_preflight":
        hard_gaps = (
            "source_gap:source_preflight_not_passed",
            "source_gap:missing_available_at_lineage",
            "source_gap:lineage_missing",
        )
        return not _has_any_gap(source_gaps, hard_gaps) and support.get("lineage", False)
    if code == "moneyflow_context":
        return not _has_any_gap(source_gaps, ("source_gap:stock_moneyflow_rank", "source_gap:stock_moneyflow_rank_components", "source_gap:moneyflow_context_missing")) and support.get("moneyflow", False)
    if code == "market_regime_context":
        return not _has_any_gap(source_gaps, ("source_gap:market_regime_context",)) and support.get("market_regime", False)
    if code == "board_theme_context":
        return not _has_any_gap(source_gaps, ("source_gap:board_theme_context",)) and support.get("board_theme", False)
    if code == "inspection_context":
        return not _has_any_gap(source_gaps, ("source_gap:inspection_context",))
    if code == "news_event_context":
        return not _has_any_gap(source_gaps, ("source_gap:news_event_context",)) and support.get("news_event", False)
    if code == "outcome_evolution_context":
        if _has_any_gap(source_gaps, ("source_gap:outcome_not_materialized",)):
            return False
        return support.get("outcome", False) or support.get("evolution", False)
    return False


def _hot_readiness_for_row(row: dict[str, Any], *, source_gaps: list[str], readiness_support: dict[str, bool]) -> dict[str, Any]:
    dimensions: list[dict[str, Any]] = []
    earned_points = 0
    missing_points = 0
    blocked_points = 0
    for dimension in HOT_READINESS_DIMENSIONS:
        ok = _readiness_dimension_ok(str(dimension["code"]), row, source_gaps, readiness_support)
        weight = int(dimension["weight"])
        earned = weight if ok else 0
        missing = 0 if ok else weight
        if ok:
            earned_points += earned
        else:
            missing_points += missing
            if dimension["priority"] == "P0":
                blocked_points += missing
        dimensions.append(
            {
                "code": dimension["code"],
                "label": dimension["label"],
                "priority": dimension["priority"],
                "weight": weight,
                "earned": earned,
                "missing": missing,
                "status": "ready" if ok else "missing",
                "gap_code": None if ok else dimension["gap_code"],
                "source_tables": list(dimension["source_tables"]),
                "handling": dimension["handling"],
            }
        )
    missing_dimensions = [dimension for dimension in dimensions if dimension["status"] != "ready"]
    top_missing = sorted(missing_dimensions, key=lambda item: (item["priority"] != "P0", -int(item["missing"]), str(item["code"])))[0] if missing_dimensions else None
    return {
        "score_pct": earned_points,
        "missing_points": missing_points,
        "blocked_points": blocked_points,
        "state": "ready" if missing_points == 0 else "blocked" if blocked_points else "degraded",
        "top_missing_dimension": top_missing,
        "gap_codes": [str(dimension["gap_code"]) for dimension in missing_dimensions if dimension.get("gap_code")],
        "dimensions": dimensions,
    }


def _hot_readiness_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "contract": "hot_model_data_readiness_v1",
            "item_count": 0,
            "average_score_pct": None,
            "average_missing_points": None,
            "ready_count": 0,
            "blocked_count": 0,
            "degraded_count": 0,
            "top_missing_dimensions": [],
        }
    total_score = sum(int(item.get("readiness_score_pct") or 0) for item in items)
    total_missing = sum(int(item.get("missing_points") or 0) for item in items)
    dimension_counts: dict[str, dict[str, Any]] = {}
    for item in items:
        for dimension in item.get("readiness_dimensions", []):
            if not isinstance(dimension, dict) or dimension.get("status") == "ready":
                continue
            code = str(dimension.get("code"))
            current = dimension_counts.setdefault(
                code,
                {
                    "code": code,
                    "label": dimension.get("label"),
                    "priority": dimension.get("priority"),
                    "weight": dimension.get("weight"),
                    "gap_code": dimension.get("gap_code"),
                    "missing_count": 0,
                    "missing_points_total": 0,
                },
            )
            current["missing_count"] += 1
            current["missing_points_total"] += int(dimension.get("missing") or 0)
    top_missing = sorted(
        dimension_counts.values(),
        key=lambda item: (-int(item["missing_points_total"]), str(item["code"])),
    )[:8]
    return {
        "contract": "hot_model_data_readiness_v1",
        "item_count": len(items),
        "average_score_pct": round(total_score / len(items), 1),
        "average_missing_points": round(total_missing / len(items), 1),
        "ready_count": sum(1 for item in items if item.get("readiness_state") == "ready"),
        "blocked_count": sum(1 for item in items if item.get("readiness_state") == "blocked"),
        "degraded_count": sum(1 for item in items if item.get("readiness_state") == "degraded"),
        "top_missing_dimensions": top_missing,
    }


def _hot_model_list_item(row: dict[str, Any], *, readiness_support: dict[str, bool] | None = None) -> dict[str, Any]:
    block_reasons = [
        *[str(item) for item in _as_list(row.get("hard_block_reasons_json")) if item],
        *[str(item) for item in _as_list(row.get("release_block_reasons_json")) if item],
    ]
    warning_reasons = [
        *[str(item) for item in _as_list(row.get("score_warning_reasons_json")) if item],
        *[str(item) for item in _as_list(row.get("release_warning_reasons_json")) if item],
    ]
    source_gaps: list[str] = []
    if row.get("score_id") is None:
        source_gaps.append("source_gap:model_score_not_materialized")
    if row.get("hot_signal_id") is None:
        source_gaps.append("source_gap:hot_signal_not_materialized")
    if row.get("buy_point_id") is None:
        source_gaps.append("source_gap:buy_point_not_materialized")
        source_gaps.append("source_gap:reference_entry_price_not_materialized")
    if _first_non_empty(row.get("p_limit_up_calibrated"), row.get("p_limit_up_raw"), row.get("paid_limit_up_probability")) is None:
        source_gaps.append("source_gap:ths_paid_probability_missing")
    if row.get("current_price") is None:
        source_gaps.append("source_gap:daily_bar_same_day_missing")
    for reason in [*block_reasons, *warning_reasons]:
        if reason.startswith("source_gap:") and reason not in source_gaps:
            source_gaps.append(reason)

    release_gate = _first_non_empty(row.get("release_gate_status"), row.get("gate_status"))
    if release_gate is None and source_gaps:
        release_gate = "blocked_data_gap"
    entry_status = _first_non_empty(row.get("buy_point_status"))
    if entry_status is None:
        entry_status = "买点未形成" if row.get("hot_signal_id") else "数据未齐"
    verification_status = "等待验证" if row.get("hot_signal_id") else "未进入验证"
    risk_summary = _hot_risk_summary(row, block_reasons, source_gaps)
    readiness = _hot_readiness_for_row(row, source_gaps=source_gaps, readiness_support=readiness_support or {})
    return {
        "hot_case_id": row.get("hot_case_id"),
        "hot_cycle_id": row.get("hot_cycle_id"),
        "stock": {"symbol": row.get("symbol"), "name": row.get("stock_name")},
        "symbol": row.get("symbol"),
        "stock_name": row.get("stock_name"),
        "signal_date": row.get("signal_date") or row.get("trade_date"),
        "trade_date": row.get("trade_date"),
        "decision_time": row.get("decision_time"),
        "lifecycle_stage": row.get("lifecycle_stage_at_decision"),
        "board_count": row.get("board_count_at_decision"),
        "ths_limit_up_probability": _first_non_empty(
            row.get("p_limit_up_calibrated"),
            row.get("paid_limit_up_probability"),
            row.get("p_limit_up_raw"),
        ),
        "p_limit_up_raw": row.get("p_limit_up_raw"),
        "p_limit_up_calibrated": row.get("p_limit_up_calibrated"),
        "model_score": row.get("model_score"),
        "model_score_label": _score_label(row),
        "model_score_stage": row.get("score_stage"),
        "score_state": row.get("scoring_state"),
        "recommendation_eligibility": row.get("recommendation_eligibility"),
        "release_gate": release_gate,
        "official_signal_allowed": row.get("official_signal_allowed"),
        "is_official_signal": row.get("is_official_signal"),
        "is_research_only": row.get("is_research_only"),
        "current_price": row.get("current_price"),
        "reference_entry_price": row.get("reference_entry_price"),
        "return_from_entry_pct": None,
        "entry_opportunity_status": entry_status,
        "mae_pct": None,
        "verification_status": verification_status,
        "risk_summary": risk_summary,
        "buy_point_status": row.get("buy_point_status"),
        "buy_point_block_reason": row.get("buy_point_block_reason"),
        "hard_block_reasons": block_reasons,
        "warning_reasons": warning_reasons,
        "source_gaps": source_gaps,
        "readiness_contract": "hot_model_data_readiness_v1",
        "readiness_score_pct": readiness["score_pct"],
        "missing_points": readiness["missing_points"],
        "blocked_points": readiness["blocked_points"],
        "readiness_state": readiness["state"],
        "top_missing_dimension": readiness["top_missing_dimension"],
        "readiness_gap_codes": readiness["gap_codes"],
        "readiness_dimensions": readiness["dimensions"],
        "data_quality": "gap" if source_gaps else "usable",
        "latest_snapshot_time": row.get("latest_snapshot_time"),
        "updated_at": row.get("latest_snapshot_time"),
    }


def _hot_risk_summary(row: dict[str, Any], block_reasons: list[str], source_gaps: list[str]) -> str:
    if row.get("buy_point_block_reason"):
        return str(row["buy_point_block_reason"])
    if block_reasons:
        return "硬阻断，暂不进入买点"
    if "source_gap:ths_paid_probability_missing" in source_gaps:
        return "缺少同花顺概率，暂不确认"
    if source_gaps:
        return "关键事实未齐，暂不确认"
    if row.get("official_signal_allowed") is False:
        return "未通过发布闸门"
    if row.get("hot_signal_id"):
        return "已进入后续验证"
    return "等待后续验证"
