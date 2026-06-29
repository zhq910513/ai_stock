from __future__ import annotations

import inspect
from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import research_service.api as api_module
from research_service.assembler import ResearchPayloadAssembler, requirements_payload
from research_service.executor import ResearchModelExecutor
from research_service.materializer import ResearchDecisionMaterializer
from research_service.main import app
from research_service.owner_client import OwnerCallResult
from research_service.owner_client import ModelOwnerClient
from research_service.repository import ResearchPayloadRepository, _hot_model_list_item, _hot_readiness_summary, jsonable
from research_service.settings import Settings
from research_service.task_registry import get_requirement


class MemoryRepository:
    def __init__(self) -> None:
        self.audit_rows: list[dict[str, Any]] = []
        self.source_rows = {
            ("source.stock_master_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "stock_name": "ZB", "exchange": "SZSE", "list_status": "listed", "source_quality_status": "usable"}
            ],
            ("source.stock_master_v1", "000760.SZ"): [
                {"symbol": "000760.SZ", "stock_name": "STOCK760", "exchange": "SZSE", "list_status": "listed", "source_quality_status": "usable"}
            ],
            ("source.trade_status_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "trade_date": "2026-06-12", "is_tradable": True, "source_quality_status": "usable", "available_at": "2026-06-12T01:00:00Z"}
            ],
            ("source.daily_bar_v1", "000759.SZ"): [
                {
                    "symbol": "000759.SZ",
                    "trade_date": "2026-06-12",
                    "instrument_id": "759",
                    "open_price": "5.29",
                    "high_price": "5.83",
                    "low_price": "5.16",
                    "close_price": "5.83",
                    "pre_close_price": "5.30",
                    "source_quality_status": "usable",
                    "available_at": "2026-06-12T07:30:00Z",
                    "lineage_id": "lineage_daily",
                }
            ],
            ("source.adjusted_daily_bar_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "trade_date": "2026-06-12", "adjusted_close": "5.83", "source_quality_status": "usable", "available_at": "2026-06-12T07:30:00Z"}
            ],
            ("source.limit_price_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "trade_date": "2026-06-12", "pre_close_price": "5.30", "up_limit_price": "5.83", "down_limit_price": "4.77", "source_quality_status": "usable", "available_at": "2026-06-12T07:30:00Z"}
            ],
            ("source.limit_event_v1", "000759.SZ"): [
                {
                    "symbol": "000759.SZ",
                    "trade_date": "2026-06-12",
                    "limit_event_type": "t_board_limit_up",
                    "is_one_word_board": False,
                    "is_break_limit": True,
                    "close_on_limit_flag": True,
                    "limit_open_count": 1,
                    "source_quality_status": "usable",
                    "available_at": "2026-06-12T07:30:00Z",
                }
            ],
            ("source.realtime_quote_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "instrument_id": "759", "trade_date": "2026-06-12", "latest_price": "5.83", "float_market_cap": "3822766125.75", "source_quality_status": "usable", "available_at": "2026-06-12T07:30:00Z"}
            ],
            ("source.minute_bar_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "instrument_id": "759", "bar_time": "2026-06-12T02:30:00Z", "close_price": "5.20", "source_quality_status": "usable", "available_at": "2026-06-12T02:31:00Z"}
            ],
            ("source.trade_tick_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "trade_date": "2026-06-12", "tick_time": "2026-06-12T02:30:00Z", "side_code": "B", "amount": "1000", "source_quality_status": "usable", "available_at": "2026-06-12T02:30:01Z"}
            ],
            ("source.stock_moneyflow_daily_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "trade_date": "2026-06-12", "main_net_inflow": "92712725", "source_quality_status": "usable", "available_at": "2026-06-12T08:30:00Z"}
            ],
            ("source.ths_paid_limit_up_probability_v1", "000759.SZ"): [
                {
                    "symbol": "000759.SZ",
                    "trade_date": "2026-06-12",
                    "paid_limit_up_probability": "76.5",
                    "source_quality_status": "usable",
                    "primary_provider": "ths",
                    "build_batch_id": "source_build_hot_20260612",
                    "available_at": "2026-06-12T00:30:00Z",
                    "updated_at": "2026-06-12T00:31:00Z",
                }
            ],
            ("source.ths_paid_limit_up_probability_v1", "000760.SZ"): [
                {
                    "symbol": "000760.SZ",
                    "trade_date": "2026-06-12",
                    "paid_limit_up_probability": "66.5",
                    "source_quality_status": "usable",
                    "primary_provider": "ths",
                    "build_batch_id": "source_build_hot_20260612",
                    "available_at": "2026-06-12T00:35:00Z",
                    "updated_at": "2026-06-12T00:36:00Z",
                }
            ],
            ("source.event_news_v1", "000759.SZ"): [
                {"symbol": "000759.SZ", "title": "event", "published_at": "2026-06-12T06:00:00Z", "available_at": "2026-06-12T06:01:00Z", "source_quality_status": "usable"}
            ],
            ("source.trade_calendar_v1", "000759.SZ"): [
                {"calendar_date": "2026-06-12", "is_trading_day": True, "source_quality_status": "usable", "available_at": "2026-01-01T00:00:00Z"}
            ],
        }
        for key in (
            "source.trade_status_v1",
            "source.daily_bar_v1",
            "source.adjusted_daily_bar_v1",
            "source.realtime_quote_v1",
            "source.minute_bar_v1",
            "source.stock_moneyflow_daily_v1",
            "source.event_news_v1",
        ):
            self.source_rows[(key, "000760.SZ")] = [
                dict(row, symbol="000760.SZ")
                for row in self.source_rows.get((key, "000759.SZ"), [])
            ]
        self.upstream_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.source_fetches: list[tuple[str, str | None, date, bool]] = []
        self.upstream_fetches: list[tuple[str, str | None, date]] = []
        self.inserted_rows: list[tuple[str, dict[str, Any]]] = []
        self.execution_audits: list[dict[str, Any]] = []
        self.hot_model_list_limits: list[int] = []

    def ready(self) -> dict[str, Any]:
        return {"status": "ready", "database_url_configured": False, "assembly_audit_ready": True}

    def fetch_hot_model_list(self, *, limit: int = 100) -> dict[str, Any]:
        self.hot_model_list_limits.append(limit)
        return {
            "contract_kind": "research_hot_model_list_v1",
            "model_code": "hot_candidates",
            "read_only": True,
            "item_count": 1,
            "gap_codes": [],
            "items": [
                {
                    "symbol": "000759.SZ",
                    "stock": {"symbol": "000759.SZ", "name": "中百集团"},
                    "signal_date": "2026-06-12",
                    "model_score": "88.5",
                    "model_score_label": "高分",
                    "entry_opportunity_status": "等待买点",
                    "risk_summary": "等待后续验证",
                    "source_gaps": [],
                    "latest_snapshot_time": "2026-06-12T08:00:00Z",
                }
            ],
        }

    def fetch_source_rows(
        self,
        table_name: str,
        *,
        symbol: str | None,
        trade_date: date,
        limit: int,
        before_or_on: bool = False,
    ) -> list[dict[str, Any]]:
        self.source_fetches.append((table_name, symbol, trade_date, before_or_on))
        rows = jsonable(self.source_rows.get((table_name, symbol or "000759.SZ"), []))
        if before_or_on:
            return rows[:limit]
        return [
            row
            for row in rows
            if row.get("trade_date") in (None, trade_date.isoformat())
            or row.get("trading_day") in (None, trade_date.isoformat())
        ][:limit]

    def fetch_hot_score_candidate_symbols(self, *, trade_date: date, limit: int = 1000) -> list[str]:
        rows: list[tuple[str, Any]] = []
        for table_name, symbol in self.source_rows:
            if table_name != "source.ths_paid_limit_up_probability_v1":
                continue
            first = self.source_rows[(table_name, symbol)][0]
            if first.get("trade_date") == trade_date.isoformat():
                rows.append((symbol, first.get("paid_limit_up_probability")))
        rows.sort(key=lambda item: item[1], reverse=True)
        return [symbol for symbol, _ in rows[:limit]]

    def fetch_hot_stage_candidate_symbols(self, *, trade_date: date, task_code: str, limit: int = 1000) -> list[str]:
        if task_code == "hot.score.auction_confirmed":
            return self.fetch_hot_score_candidate_symbols(trade_date=trade_date, limit=limit)
        rows: list[tuple[str, Any]] = []
        for table_name, symbol in self.upstream_rows:
            if table_name != "decision_hot.hot_decision_case_v1":
                continue
            cases = self.upstream_rows[(table_name, symbol)]
            if not any(str(row.get("trade_date")) == trade_date.isoformat() for row in cases):
                continue
            score_rows = self.upstream_rows.get(("decision_hot.hot_score_fact_v1", symbol), [])
            if not score_rows:
                continue
            score = score_rows[0]
            rows.append(
                (
                    symbol,
                    score.get("official_hot_score")
                    or score.get("open_5m_confirmed_score")
                    or score.get("auction_confirmed_score")
                    or score.get("pre_auction_score")
                    or 0,
                )
            )
        rows.sort(key=lambda item: item[1], reverse=True)
        return [symbol for symbol, _ in rows[:limit]]

    def fetch_upstream_rows(self, table_name: str, *, symbol: str | None, trade_date: date, limit: int = 20) -> list[dict[str, Any]]:
        self.upstream_fetches.append((table_name, symbol, trade_date))
        return jsonable(self.upstream_rows.get((table_name, symbol or "000759.SZ"), []))[:limit]

    def previous_trading_day(self, trade_date: date) -> date | None:
        return trade_date - timedelta(days=1)

    def fetch_hot_case_upstream_rows(self, table_name: str, *, symbol: str | None, trade_date: date, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.upstream_rows.get((table_name, symbol or "000759.SZ"))
        if rows is not None:
            return jsonable(rows)[:limit]
        return self.fetch_upstream_rows(table_name, symbol=symbol, trade_date=trade_date, limit=limit)

    def fetch_hot_release_upstream_rows(self, table_name: str, *, symbol: str | None, trade_date: date, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.upstream_rows.get((table_name, symbol or "000759.SZ"))
        if rows is not None:
            return jsonable(rows)[:limit]
        return self.fetch_upstream_rows(table_name, symbol=symbol, trade_date=trade_date, limit=limit)

    def persist_assembly_audit(self, **kwargs: Any) -> bool:
        self.audit_rows.append(kwargs)
        return True

    def insert_row(self, table_name: str, values: dict[str, Any]) -> bool:
        self.inserted_rows.append((table_name, values))
        return True

    def persist_execution_audit(self, **kwargs: Any) -> bool:
        self.execution_audits.append(kwargs)
        return True


class PassingSourceClient:
    def release_preflight(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "model_code": kwargs["model_code"],
            "model_phase": kwargs["model_phase"],
            "trade_date": kwargs["trade_date"].isoformat(),
            "can_release_official_signal": True,
            "coverage_status": "passed",
            "freshness_status": "passed",
            "blocking_reasons": [],
            "degraded_reasons": [],
        }


class BlockingSourceClient:
    def release_preflight(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "can_release_official_signal": False,
            "coverage_status": "blocked",
            "freshness_status": "passed",
            "blocking_reasons": ["missing:source.daily_bar_v1.close_price"],
            "degraded_reasons": [],
        }


class FakeOwnerClient:
    def __init__(self, *, mismatched_hot_buy_case: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.mismatched_hot_buy_case = mismatched_hot_buy_case

    def call_owner(self, task: Any, *, payload: dict[str, Any], run_id: str, as_of_time_utc: str | None) -> OwnerCallResult:
        self.calls.append((task.task_code, payload))
        if task.task_code == "hot.score.auction_confirmed":
            body = {
                "model_name": "hot_candidates",
                "model_version": "test_hot_v1",
                "structured_output": {
                    "score_compute": {
                        "hot_case_id": "hotcase-test",
                        "stage_scores": {"auction_confirmed_score": "88.5"},
                        "source_visibility_audit": {"hard_block_codes": [], "warning_codes": []},
                        "score_state": "scored",
                    }
                },
                "contract_gaps": [],
            }
        elif task.task_code == "hot.release_gate.preopen":
            hot_case_id = _payload_hot_case_id(payload)
            hot_cycle_id = _payload_hot_cycle_id(payload)
            symbol = str(payload.get("symbol") or "000759.SZ")
            body = {
                "model_name": "hot_candidates",
                "model_version": "test_hot_v1",
                "structured_output": {
                    "release_gate_result": {
                        "hot_case_id": hot_case_id,
                        "release_gate": {
                            "gate_status": "blocked",
                            "official_signal_allowed": False,
                            "signal_stage": "research_sample",
                            "block_reasons": ["release_gate_not_passed"],
                        },
                        "hot_signal": {
                            "hot_signal_id": f"hotsig-{symbol}",
                            "hot_case_id": hot_case_id,
                            "hot_cycle_id": hot_cycle_id,
                            "symbol": symbol,
                            "signal_date": "2026-06-12",
                            "model_version": "test_hot_v1",
                            "model_score": "88.5",
                            "signal_stage": "research_sample",
                            "is_official_signal": False,
                            "is_research_only": True,
                            "release_gate_status": "blocked",
                            "release_gate_reason": ["release_gate_not_passed"],
                        },
                    }
                },
                "contract_gaps": ["release_gate_not_passed"],
            }
        elif task.task_code == "hot.buy_point.open_5m":
            hot_case_id = _payload_hot_case_id(payload)
            hot_cycle_id = _payload_hot_cycle_id(payload)
            symbol = str(payload.get("symbol") or "000759.SZ")
            owner_hot_case_id = f"owner-hotcase-{symbol}" if self.mismatched_hot_buy_case else hot_case_id
            owner_hot_cycle_id = f"owner-hotcycle-{symbol}" if self.mismatched_hot_buy_case else hot_cycle_id
            owner_hot_signal_id = f"owner-hotsig-{symbol}" if self.mismatched_hot_buy_case else f"hotsig-{symbol}"
            owner_buy_point_id = f"owner-hotbuy-{symbol}" if self.mismatched_hot_buy_case else f"hotbuy-{symbol}"
            body = {
                "model_name": "hot_candidates",
                "model_version": "test_hot_v1",
                "structured_output": {
                    "buy_point_result": {
                        "hot_case_id": owner_hot_case_id,
                        "hot_signal": {
                            "hot_signal_id": owner_hot_signal_id,
                            "hot_case_id": owner_hot_case_id,
                            "hot_cycle_id": owner_hot_cycle_id,
                            "symbol": symbol,
                            "signal_date": "2026-06-12",
                            "model_version": "test_hot_v1",
                            "model_score": "88.5",
                            "signal_stage": "research_sample",
                            "is_official_signal": False,
                            "is_research_only": True,
                            "release_gate_status": "blocked",
                            "release_gate_reason": ["release_gate_not_passed"],
                        },
                        "buy_point": {
                            "buy_point_id": owner_buy_point_id,
                            "hot_signal_id": owner_hot_signal_id,
                            "hot_case_id": owner_hot_case_id,
                            "hot_cycle_id": owner_hot_cycle_id,
                            "adapter_code": "hot_candidates_buy_point_adapter",
                            "adapter_version": "test_buy_point_v1",
                            "calc_stage": "open_5m_confirmed",
                            "reference_entry_price": "5.20",
                            "entry_price_low": "5.174000",
                            "entry_price_high": "5.226000",
                            "target_price": "5.720000",
                            "invalidation_price": "4.992000",
                            "risk_reward_ratio": "2.000000",
                            "buy_point_status": "blocked",
                            "block_reason": "release_gate_not_passed",
                            "calculated_at": "2026-06-12T01:35:00Z",
                            "data_as_of": "2026-06-12T01:35:00Z",
                            "is_first_valid": False,
                            "is_frozen_reference": False,
                            "decision_trace_json": {"block_reasons": ["release_gate_not_passed"]},
                        },
                    }
                },
                "contract_gaps": ["release_gate_not_passed"],
            }
        elif task.task_code == "memory.seed.from_hot_signals":
            body = {
                "model_name": "candidate_memory",
                "model_version": "test_memory_v1",
                "structured_output": {
                    "memory_seed": {
                        "memory_seed_id": "seed-1",
                        "source_model": "hot_candidates",
                        "first_source_signal_id": "hotsig-1",
                        "symbol": "000759",
                        "seed_priority": "research_memory",
                        "seed_reasons": ["historical_attention_memory"],
                        "seed_status": "accepted",
                        "created_at": "2026-06-12T08:00:00Z",
                        "payload_hash": "seed-hash",
                    },
                    "memory_entity": {
                        "memory_entity_id": "mem-1",
                        "memory_seed_id": "seed-1",
                        "symbol": "000759",
                        "first_source_model": "hot_candidates",
                        "first_source_signal_id": "hotsig-1",
                        "memory_status": "observing",
                        "base_ttl_days": 40,
                        "dynamic_ttl_adjustment_days": 0,
                        "ttl_effective_days": 40,
                        "memory_age_days": 0,
                        "merge_action": "create_new_entity",
                        "payload_hash": "entity-hash",
                    },
                },
                "contract_gaps": [],
            }
        else:
            body = {
                "model_name": "ambush_watchlist",
                "model_version": "test_ambush_v1",
                "structured_output": {
                    "phase2": {
                        "valley_watch": {
                            "valley_id": "valley-1",
                            "symbol": "000759.SZ",
                            "as_of_trading_day": "2026-06-12",
                            "trade_date": "2026-06-12",
                            "pool_state": "research_only",
                            "valley_status": "valley_watch",
                            "window_days": 60,
                            "price_adjustment_mode": "source_adjusted",
                            "formula_version": "ambush_phase2_test",
                            "formula_governance": {"version": "test"},
                            "payload_hash": "valley-hash",
                            "calculated_at": "2026-06-12T08:00:00Z",
                        },
                        "effective_turn_anchor": {
                            "turn_anchor_id": "turn-1",
                            "valley_id": "valley-1",
                            "symbol": "000759.SZ",
                            "as_of_trading_day": "2026-06-12",
                            "trade_date": "2026-06-12",
                            "l1_status": "accepted",
                            "pool_target": "effective_turn_pool_research_only",
                            "price_adjustment_mode": "source_adjusted",
                            "formula_version": "ambush_phase2_test",
                            "formula_governance": {"version": "test"},
                            "payload_hash": "turn-hash",
                            "calculated_at": "2026-06-12T08:00:00Z",
                        },
                        "transition_audit": {
                            "transition_id": "transition-1",
                            "symbol": "000759.SZ",
                            "from_pool": "valley_watch_pool",
                            "to_pool": "effective_turn_pool",
                            "decision_result": "research_only",
                            "trigger_event": "phase2_valley_turn",
                            "trigger_as_of_time": "2026-06-12T08:00:00Z",
                            "trigger_snapshot_type": "close_confirmed",
                            "trigger_feature": {},
                            "decision_rule_version": "ambush_phase2_test",
                            "created_by_job": "test",
                            "formula_governance": {"version": "test"},
                            "transition_hash": "transition-hash",
                            "calculated_at": "2026-06-12T08:00:00Z",
                        },
                    }
                },
                "contract_gaps": [],
            }
        return OwnerCallResult(
            owner_service=task.owner_service,
            endpoint=task.endpoint,
            url=f"http://owner{task.endpoint}",
            request_body={"payload": payload, "run_id": run_id, "as_of_time_utc": as_of_time_utc},
            status_code=200,
            response_body=body,
        )


def _first_payload_upstream(payload: dict[str, Any], table_name: str) -> dict[str, Any]:
    upstream = payload.get("upstream_model_facts") if isinstance(payload.get("upstream_model_facts"), dict) else {}
    table_rows = upstream.get(table_name) if isinstance(upstream.get(table_name), dict) else {}
    for rows in table_rows.values():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0]
    return {}


def _payload_hot_case_id(payload: dict[str, Any]) -> str:
    case = _first_payload_upstream(payload, "decision_hot.hot_decision_case_v1")
    score = _first_payload_upstream(payload, "decision_hot.hot_score_fact_v1")
    return str(case.get("hot_case_id") or score.get("hot_case_id") or "hotcase-test")


def _payload_hot_cycle_id(payload: dict[str, Any]) -> str:
    case = _first_payload_upstream(payload, "decision_hot.hot_decision_case_v1")
    return str(case.get("hot_cycle_id") or "hotcycle-test")


def _assembler(repo: MemoryRepository | None = None, source_client: Any | None = None) -> ResearchPayloadAssembler:
    return ResearchPayloadAssembler(
        repository=repo or MemoryRepository(),
        source_client=source_client or PassingSourceClient(),
        settings=Settings(default_symbols="000759.SZ"),
    )


def _executor(repo: MemoryRepository, owner: FakeOwnerClient | None = None) -> ResearchModelExecutor:
    return ResearchModelExecutor(
        assembler=_assembler(repo),
        repository=repo,
        owner_client=owner or FakeOwnerClient(),
        materializer=ResearchDecisionMaterializer(repo),  # type: ignore[arg-type]
    )


def test_requirements_cover_25_owner_tasks() -> None:
    payload = requirements_payload()

    assert payload["assembler_contract"] == "research_model_payload_assembler_v1"
    assert payload["task_count"] == 25
    assert all(not any(str(src).startswith("raw") for src in task["source_tables"]) for task in payload["tasks"])


def test_official_release_requirements_do_not_wait_for_their_own_outputs() -> None:
    payload = requirements_payload()
    tasks = {task["task_code"]: task for task in payload["tasks"]}

    hot_release = tasks["hot.release_gate.preopen"]
    assert "source.minute_bar_v1" not in hot_release["source_tables"]
    assert "source.ths_paid_limit_up_probability_v1" in tasks["hot.score.auction_confirmed"]["source_tables"]
    assert "source.ths_paid_limit_up_probability_v1" not in hot_release["source_tables"]
    assert hot_release["upstream_tables"] == (
        "decision_hot.hot_score_fact_v1",
        "decision_hot.hot_evidence_snapshot_v1",
    )

    memory_release = tasks["memory.release_gate.close"]
    assert memory_release["upstream_tables"] == (
        "decision_memory.memory_entity_v1",
        "decision_memory.memory_pre_signal_case_v1",
        "decision_memory.memory_score_fact_v1",
    )
    assert "decision_memory.memory_signal_fact_v1" not in memory_release["upstream_tables"]

    ambush_release = tasks["ambush.phase3.release_gate.close"]
    assert ambush_release["upstream_tables"] == (
        "decision_ambush.valley_watch_pool_v1",
        "decision_ambush.effective_turn_anchor_v1",
        "decision_ambush.effective_turn_pool_v1",
    )
    assert "decision_ambush.ambush_signal_fact_v1" not in ambush_release["upstream_tables"]
    assert "source.limit_price_v1" in tasks["t_relay.day2.watch.rolling_5m"]["source_tables"]
    assert "source.limit_price_v1" in tasks["t_relay.day2.post_entry.monitor"]["source_tables"]
    assert tasks["t_relay.day2.trigger.rolling_5m"]["upstream_tables"] == (
        "decision_t_relay.t_board_day1_candidate_v1",
        "decision_t_relay.t_board_day2_watch_snapshot_v1",
    )
    assert tasks["t_relay.day2.trigger.rolling_5m"]["official_publish"] is False
    assert tasks["t_relay.day2.trigger.rolling_5m"]["source_preflight_required"] is False
    assert tasks["t_relay.observation.monitor.snapshot_5m"]["source_tables"] == ()
    assert tasks["t_relay.observation.monitor.snapshot_5m"]["upstream_tables"] == ()
    assert tasks["t_relay.observation.monitor.snapshot_5m"]["official_publish"] is False


def test_t_relay_day1_assembles_real_source_payload_and_audit() -> None:
    repo = MemoryRepository()
    assembler = _assembler(repo)

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="t_relay.day1.scan.close",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    assert result.payload_assembly_status == "assembled_research_payload"
    assert result.payload["rows"][0]["up_limit_price"] == "5.83"
    assert result.payload["rows"][0]["stock_name"] == "ZB"
    assert result.payload["rows"][0]["name"] == "ZB"
    assert result.payload["payload_assembly_contract"] == "research_model_payload_assembler_v1"
    assert result.payload_hash
    assert result.audit_persisted is True
    assert repo.audit_rows[0]["payload_hash"] == result.payload_hash


def test_official_release_blocks_when_source_preflight_fails() -> None:
    assembler = _assembler(source_client=BlockingSourceClient())

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="hot.release_gate.preopen",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    assert result.payload_assembly_status == "blocked_data_gap"
    assert "source_gap:source_preflight_not_passed" in result.gap_codes
    assert result.payload["source_preflight"]["can_release_official_signal"] is False


def test_t_relay_day2_trigger_does_not_use_release_preflight() -> None:
    repo = MemoryRepository()
    repo.upstream_rows[("decision_t_relay.t_board_day1_candidate_v1", "000759.SZ")] = [
        {
            "day1_candidate_id": "day1-1",
            "canonical_symbol": "000759.SZ",
            "trade_date": "2026-06-12",
            "candidate_status": "qualified",
            "source_gap_codes": [],
        }
    ]
    repo.upstream_rows[("decision_t_relay.t_board_day2_watch_snapshot_v1", "000759.SZ")] = [
        {
            "day2_watch_snapshot_id": "watch-1",
            "day1_candidate_id": "day1-1",
            "canonical_symbol": "000759.SZ",
            "day2_trade_date": "2026-06-13",
            "as_of_time": "2026-06-13T01:35:00Z",
            "watch_status": "near_limit_reached",
            "near_limit_flag": True,
            "distance_to_up_limit_pct": "0.000000",
            "source_gap_codes": [],
            "request_payload": {"payload": {"trade_ticks": [{"amount": "1"}]}, "rows": [{"symbol": "000759.SZ"}]},
            "result_payload": {"debug": "large-result"},
            "game_hypothesis_payload": {"debug": "large-game"},
        }
    ]
    assembler = _assembler(repo, source_client=BlockingSourceClient())

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="t_relay.day2.trigger.rolling_5m",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 13),
        )
    )

    row = result.payload["payload"]
    assert result.payload_assembly_status == "assembled_research_payload"
    assert result.source_preflight is None
    assert "source_gap:source_preflight_not_passed" not in result.gap_codes
    assert row["day1_candidate_status"] == "qualified"
    assert row["watch_snapshot"]["near_limit_flag"] is True
    assert row["watch_snapshot"]["day2_watch_snapshot_id"] == "watch-1"
    assert "request_payload" not in row["watch_snapshot"]
    assert "result_payload" not in row["watch_snapshot"]
    assert "game_hypothesis_payload" not in row["watch_snapshot"]


def test_t_relay_owner_client_does_not_send_rows_for_day2_trigger() -> None:
    task = get_requirement("t_relay.day2.trigger.rolling_5m")
    assert task is not None
    calls: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"structured_output": {"day2_entry_trigger": {"entry_trigger_status": "triggered"}}}

    class Client:
        def post(self, url: str, *, json: dict[str, Any], timeout: float) -> Response:  # noqa: ANN001
            calls.append({"url": url, "json": json, "timeout": timeout})
            return Response()

    owner = ModelOwnerClient(
        hot_candidates_base_url="http://hot",
        candidate_memory_base_url="http://memory",
        ambush_watchlist_base_url="http://ambush",
        t_board_relay_base_url="http://tboard",
        request_timeout_seconds=12,
        client=Client(),  # type: ignore[arg-type]
    )

    owner.call_owner(
        task,
        payload={"payload": {"symbol": "000759.SZ"}, "rows": [{"symbol": "000759.SZ"}, {"symbol": "000760.SZ"}]},
        run_id="run-1",
        as_of_time_utc="2026-06-13T01:35:00Z",
    )

    body = calls[0]["json"]
    assert body["payload"] == {"symbol": "000759.SZ"}
    assert "rows" not in body
    assert "row" not in body


def test_t_relay_observation_snapshot_assembles_without_source_or_upstream() -> None:
    repo = MemoryRepository()
    assembler = _assembler(repo, source_client=BlockingSourceClient())

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="t_relay.observation.monitor.snapshot_5m",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 24),
            as_of_time_utc="2026-06-24T02:15:00Z",
            persist_audit=False,
            extra_context={
                "scheduler_materialized_instance": {
                    "task_code": "t_relay.observation.monitor.snapshot_5m",
                    "scheduled_at": "2026-06-24T01:35:00Z",
                    "captured_late": True,
                }
            },
        )
    )

    snapshot_payload = result.payload["payload"]
    assert result.payload_assembly_status == "assembled_research_payload"
    assert result.source_refs == []
    assert result.upstream_refs == []
    assert repo.upstream_fetches == []
    assert result.audit_persisted is False
    assert snapshot_payload["trade_date"] == "2026-06-24"
    assert snapshot_payload["limit"] == 500
    assert snapshot_payload["monitor_interval_minutes"] == 5
    assert snapshot_payload["as_of_time_utc"] == "2026-06-24T02:15:00+00:00"
    assert snapshot_payload["scheduler_context"]["captured_late"] is True


def test_t_relay_owner_client_wraps_observation_snapshot_without_rows() -> None:
    task = get_requirement("t_relay.observation.monitor.snapshot_5m")
    assert task is not None
    calls: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"structured_output": {"observation_monitor_snapshot": {"snapshot_count": 4}}}

    class Client:
        def post(self, url: str, *, json: dict[str, Any], timeout: float) -> Response:  # noqa: ANN001
            calls.append({"url": url, "json": json, "timeout": timeout})
            return Response()

    owner = ModelOwnerClient(
        hot_candidates_base_url="http://hot",
        candidate_memory_base_url="http://memory",
        ambush_watchlist_base_url="http://ambush",
        t_board_relay_base_url="http://tboard",
        request_timeout_seconds=12,
        client=Client(),  # type: ignore[arg-type]
    )

    owner.call_owner(
        task,
        payload={
            "payload": {
                "trade_date": "2026-06-24",
                "limit": 500,
                "monitor_interval_minutes": 5,
                "as_of_time_utc": "2026-06-24T02:15:00+00:00",
            },
            "trade_date": "2026-06-24",
        },
        run_id="snapshot-run-1",
        as_of_time_utc="2026-06-24T02:15:00Z",
    )

    call = calls[0]
    body = call["json"]
    assert call["url"] == "http://tboard/t-board-relay/observation-monitor/snapshot"
    assert body["payload"]["limit"] == 500
    assert body["trade_date"] == "2026-06-24"
    assert body["run_id"] == "snapshot-run-1"
    assert body["as_of_time_utc"] == "2026-06-24T02:15:00Z"
    assert "rows" not in body
    assert "row" not in body


def test_hot_release_reads_score_and_evidence_through_case_link() -> None:
    repo = MemoryRepository()
    repo.upstream_rows[("decision_hot.hot_score_fact_v1", "000759.SZ")] = [
        {
            "score_id": 1,
            "hot_case_id": "hotcase-test",
            "score_stage": "auction_confirmed_score",
            "scoring_state": "blocked",
            "hard_block_reasons_json": ["source_gap:score_blocked"],
        }
    ]
    repo.upstream_rows[("decision_hot.hot_evidence_snapshot_v1", "000759.SZ")] = [
        {
            "evidence_id": 1,
            "hot_case_id": "hotcase-test",
            "evidence_domain": "source.daily_bar_v1",
            "evidence_status": "usable",
            "quality_status": "usable",
        }
    ]
    assembler = _assembler(repo)

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="hot.release_gate.preopen",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    assert "source_gap:decision_hot_hot_score_fact_missing" not in result.gap_codes
    assert "source_gap:decision_hot_hot_evidence_snapshot_missing" not in result.gap_codes
    assert "source_gap:score_blocked" in result.gap_codes
    assert result.payload_assembly_status == "blocked_data_gap"
    assert result.payload["upstream_model_facts"]["decision_hot.hot_score_fact_v1"]["000759.SZ"][0]["hot_case_id"] == "hotcase-test"


def test_missing_source_stays_gap_coded() -> None:
    repo = MemoryRepository()
    repo.source_rows.pop(("source.limit_price_v1", "000759.SZ"))
    assembler = _assembler(repo)

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="t_relay.day1.scan.close",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    assert result.payload_assembly_status == "blocked_data_gap"
    assert "source_gap:limit_price_missing" in result.gap_codes
    assert result.payload["rows"][0]["up_limit_price"] is None


def test_t_relay_day2_keeps_degradable_day1_gap_as_warning() -> None:
    repo = MemoryRepository()
    repo.upstream_rows[("decision_t_relay.t_board_day1_candidate_v1", "000759.SZ")] = [
        {
            "day1_candidate_id": "day1-1",
            "canonical_symbol": "000759.SZ",
            "trade_date": "2026-06-12",
            "candidate_status": "rejected",
            "reject_reason": "not_t_board",
            "source_gap_codes": ["source_gap:seal_order_snapshot_missing"],
        }
    ]
    assembler = _assembler(repo)

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="t_relay.day2.watch.rolling_5m",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 13),
        )
    )

    row = result.payload["payload"]
    assert result.payload_assembly_status == "assembled_research_payload"
    assert result.gap_codes == []
    assert "source_gap:seal_order_snapshot_missing" in result.warnings
    assert row["day1_candidate_status"] == "rejected"
    assert row["up_limit_price"] == "5.83"
    assert row["last_price_at_watch"] == "5.20"
    assert row["distance_to_up_limit_pct"] == "0.108062"
    assert row["monitor_interval_minutes"] == 5
    assert row["monitor_check_time"] == "10:30:00"
    assert row["order_consumption_side"] == "ASK"
    assert row["order_consumption_amount"] == "1000"
    assert repo.upstream_fetches == [
        ("decision_t_relay.t_board_day1_candidate_v1", "000759.SZ", date(2026, 6, 12))
    ]
    assert result.upstream_refs[0].trade_date == "2026-06-12"
    assert result.trade_date == "2026-06-13"
    assert repo.audit_rows[0]["status"] == "assembled_research_payload"


def test_t_relay_post_entry_keeps_trigger_research_gaps_as_warning_and_builds_monitor_payload() -> None:
    repo = MemoryRepository()
    repo.source_rows[("source.minute_bar_v1", "000759.SZ")] = [
        {"symbol": "000759.SZ", "bar_time": "2026-06-13T01:35:00Z", "close_price": "5.83", "source_quality_status": "usable", "available_at": "2026-06-13T01:36:00Z"},
        {"symbol": "000759.SZ", "bar_time": "2026-06-13T02:00:00Z", "close_price": "5.70", "source_quality_status": "usable", "available_at": "2026-06-13T02:01:00Z"},
        {"symbol": "000759.SZ", "bar_time": "2026-06-13T07:00:00Z", "close_price": "5.83", "source_quality_status": "usable", "available_at": "2026-06-13T07:01:00Z"},
    ]
    repo.source_rows[("source.limit_event_v1", "000759.SZ")] = [
        {
            "symbol": "000759.SZ",
            "trade_date": "2026-06-13",
            "limit_event_type": "limit_up",
            "close_on_limit_flag": True,
            "source_quality_status": "usable",
            "available_at": "2026-06-13T07:01:00Z",
        }
    ]
    repo.upstream_rows[("decision_t_relay.t_board_day2_entry_trigger_v1", "000759.SZ")] = [
        {
            "entry_trigger_id": "entry-1",
            "day1_candidate_id": "day1-1",
            "canonical_symbol": "000759.SZ",
            "day2_trade_date": "2026-06-13",
            "trigger_time": "09:35:00",
            "last_price_at_trigger": "5.83",
            "source_gap_codes": [
                "source_gap:seal_order_snapshot_missing",
                "source_gap:dynamic_feature_bundle_missing",
                "source_gap:near_limit_order_absorption_missing",
            ],
        }
    ]
    assembler = _assembler(repo)

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="t_relay.day2.post_entry.monitor",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 13),
            as_of_time_utc="2026-06-13T07:00:00Z",
        )
    )

    row = result.payload["payload"]
    assert result.payload_assembly_status == "assembled_research_payload"
    assert result.gap_codes == []
    assert "source_gap:dynamic_feature_bundle_missing" in result.warnings
    assert row["entry_trigger_id"] == "entry-1"
    assert row["up_limit_price"] == "5.83"
    assert row["post_entry_board_opened"] is True
    assert row["first_board_open_time_after_entry"] == "10:00:00"
    assert row["close_on_limit_flag"] is True
    assert row["lowest_price_after_entry"] == "5.70"


def test_upstream_sample_marker_still_blocks_payload() -> None:
    repo = MemoryRepository()
    repo.upstream_rows[("decision_t_relay.t_board_day1_candidate_v1", "000759.SZ")] = [
        {
            "day1_candidate_id": "day1-1",
            "canonical_symbol": "000759.SZ",
            "trade_date": "2026-06-12",
            "run_id": "sample-day1-candidate",
            "source_gap_codes": ["source_gap:seal_order_snapshot_missing"],
        }
    ]
    assembler = _assembler(repo)

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="t_relay.day2.watch.rolling_5m",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    assert result.payload_assembly_status == "blocked_data_gap"
    assert "source_gap:seal_order_snapshot_missing" in result.warnings
    assert "source_gap:seal_order_snapshot_missing" not in result.gap_codes
    assert "payload_gap:upstream_sample_payload_marker_present" in result.gap_codes
    assert repo.audit_rows[0]["status"] == "blocked_data_gap"


def test_api_uses_injected_assembler(monkeypatch) -> None:  # noqa: ANN001
    assembler = _assembler()
    monkeypatch.setattr(api_module, "build_assembler", lambda: assembler)
    client = TestClient(app)

    response = client.post(
        "/research/model-payload/assemble",
        json={"task_code": "t_relay.day1.scan.close", "symbol": "000759.SZ", "trade_date": "2026-06-12"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payload_assembly_contract"] == "research_model_payload_assembler_v1"
    assert body["payload"]["rows"][0]["symbol"] == "000759.SZ"


def test_hot_model_list_api_uses_repository_projection(monkeypatch) -> None:  # noqa: ANN001
    repo = MemoryRepository()
    monkeypatch.setattr(api_module, "build_repository", lambda: repo)
    client = TestClient(app)

    response = client.get("/research/model-list/hot?limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_kind"] == "research_hot_model_list_v1"
    assert body["model_code"] == "hot_candidates"
    assert body["read_only"] is True
    assert body["items"][0]["stock"]["name"] == "中百集团"
    assert body["items"][0]["model_score"] == "88.5"
    assert repo.hot_model_list_limits == [5]


def test_hot_model_list_item_reports_weighted_data_readiness() -> None:
    row = {
        "hot_case_id": "hotcase-1",
        "hot_cycle_id": "cycle-1",
        "symbol": "000759.SZ",
        "stock_name": "中百集团",
        "trade_date": date(2026, 6, 12),
        "p_limit_up_calibrated": None,
        "p_limit_up_raw": None,
        "paid_limit_up_probability": None,
        "score_id": None,
        "hot_signal_id": None,
        "buy_point_id": None,
        "current_price": None,
        "hard_block_reasons_json": ["source_gap:source_preflight_not_passed"],
        "release_block_reasons_json": [],
        "score_warning_reasons_json": [],
        "release_warning_reasons_json": [],
    }
    item = _hot_model_list_item(
        row,
        readiness_support={
            "trade_status": True,
            "trade_calendar": True,
            "lineage": False,
        },
    )

    assert item["readiness_contract"] == "hot_model_data_readiness_v1"
    assert item["readiness_score_pct"] == 20
    assert item["missing_points"] == 80
    assert item["blocked_points"] == 57
    assert item["readiness_state"] == "blocked"
    assert item["top_missing_dimension"]["code"] == "ths_paid_probability"
    assert "source_gap:ths_paid_probability_missing" in item["readiness_gap_codes"]
    assert sum(dimension["weight"] for dimension in item["readiness_dimensions"]) == 100


def test_hot_model_list_projection_uses_current_case_per_symbol() -> None:
    source = inspect.getsource(ResearchPayloadRepository.fetch_hot_model_list)

    assert "row_number() over" in source
    assert "partition by base_case.symbol, base_case.trade_date" in source
    assert "where score.hot_case_id = base_case.hot_case_id" in source
    assert "current_case_rank = 1" in source


def test_hot_readiness_summary_uses_null_average_when_no_rows() -> None:
    summary = _hot_readiness_summary([])

    assert summary["contract"] == "hot_model_data_readiness_v1"
    assert summary["item_count"] == 0
    assert summary["average_score_pct"] is None
    assert summary["average_missing_points"] is None


def test_execution_blocks_before_owner_when_assembly_has_gap() -> None:
    repo = MemoryRepository()
    repo.source_rows.pop(("source.limit_price_v1", "000759.SZ"))
    owner = FakeOwnerClient()
    executor = _executor(repo, owner)

    result = executor.run(
        api_module.ModelExecutionRunRequest(
            task_code="t_relay.day1.scan.close",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    assert result.execution_status == "blocked_data_gap"
    assert result.owner_called is False
    assert result.accepted is False
    assert owner.calls == []
    assert repo.execution_audits[0]["execution_status"] == "blocked_data_gap"


def test_execution_calls_hot_owner_and_materializes_decision_tables() -> None:
    repo = MemoryRepository()
    executor = _executor(repo)

    result = executor.run(
        api_module.ModelExecutionRunRequest(
            task_code="hot.score.auction_confirmed",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    tables = [table for table, _ in repo.inserted_rows]
    decision_rows = [row for table, row in repo.inserted_rows if table == "decision_hot.hot_decision_case_v1"]
    assert result.execution_status == "materialized"
    assert result.accepted is True
    assert "decision_hot.hot_cycle_v1" in tables
    assert "decision_hot.hot_decision_case_v1" in tables
    assert "decision_hot.hot_score_fact_v1" in tables
    assert decision_rows[0]["batch_id"] is not None
    assert decision_rows[0]["candidate_id"] is not None
    assert decision_rows[0]["instrument_id"] == 759
    assert decision_rows[0]["p_limit_up_raw"] == "76.5"
    assert ("source.daily_bar_v1", "000759.SZ", date(2026, 6, 12), True) in repo.source_fetches
    assert ("source.ths_paid_limit_up_probability_v1", "000759.SZ", date(2026, 6, 12), False) in repo.source_fetches
    assert repo.execution_audits[0]["accepted"] is True


def test_hot_score_uses_adjusted_daily_when_unadjusted_daily_is_missing() -> None:
    repo = MemoryRepository()
    repo.source_rows.pop(("source.daily_bar_v1", "000759.SZ"))
    repo.source_rows[("source.adjusted_daily_bar_v1", "000759.SZ")] = [
        {
            "symbol": "000759.SZ",
            "trade_date": "2026-06-12",
            "adjustment_mode": "qfq",
            "adjusted_open": "5.29",
            "adjusted_high": "5.83",
            "adjusted_low": "5.16",
            "adjusted_close": "5.83",
            "source_quality_status": "usable",
            "available_at": "2026-06-12T07:30:00Z",
            "lineage_id": "lineage_adjusted",
            "build_batch_id": "source_build_adjusted",
        }
    ]
    owner = FakeOwnerClient()
    executor = _executor(repo, owner)

    result = executor.run(
        api_module.ModelExecutionRunRequest(
            task_code="hot.score.auction_confirmed",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    payload = owner.calls[0][1]
    assert result.execution_status == "materialized"
    assert "source_gap:daily_bar_missing" not in result.assembly.gap_codes
    assert "source_gap:daily_bar_missing_using_adjusted_daily_bar" in result.assembly.warnings
    assert payload["daily_bar_source"] == "source.adjusted_daily_bar_v1"
    assert payload["daily_bar_fallback_used"] is True
    assert payload["instrument_id"] == "759"
    assert payload["daily_bars"][0]["close_price"] == "5.83"
    assert payload["daily_bars"][0]["daily_bar_source"] == "source.adjusted_daily_bar_v1"
    assert payload["reference_entry_price"] == "5.83"


def test_adjusted_daily_fallback_does_not_unlock_non_hot_score_tasks() -> None:
    repo = MemoryRepository()
    repo.source_rows.pop(("source.daily_bar_v1", "000759.SZ"))
    assembler = _assembler(repo)

    result = assembler.assemble(
        api_module.ModelPayloadAssembleRequest(
            task_code="ambush.source_capability.audit",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    assert result.payload_assembly_status == "blocked_data_gap"
    assert "source_gap:daily_bar_missing" in result.gap_codes
    assert "source_gap:daily_bar_missing_using_adjusted_daily_bar" not in result.warnings


def test_scheduler_hot_score_execution_fans_out_paid_probability_candidates() -> None:
    repo = MemoryRepository()
    owner = FakeOwnerClient()
    executor = _executor(repo, owner)

    result = executor.run(
        api_module.ModelExecutionRunRequest(
            task_code="hot.score.auction_confirmed",
            symbol="000063.SZ",
            symbols=["000063.SZ"],
            trade_date=date(2026, 6, 12),
            run_id="scheduler-hot-score",
            extra_context={"scheduler_task_instance_id": "task-hot-score-1"},
        )
    )

    called_symbols = [payload["symbol"] for _, payload in owner.calls]
    assert result.execution_status == "materialized"
    assert result.accepted is True
    assert result.symbol is None
    assert result.materialized_counts["fanout_total"] == 2
    assert result.materialized_counts["fanout_materialized"] == 2
    assert called_symbols == ["000759.SZ", "000760.SZ"]
    assert all(symbol != "000063.SZ" for symbol in called_symbols)


def test_scheduler_hot_buy_point_fans_out_scored_cases_and_materializes_research_only_signal() -> None:
    repo = MemoryRepository()
    for symbol, score in (("000759.SZ", "88.5"), ("000760.SZ", "76.5")):
        repo.upstream_rows[("decision_hot.hot_decision_case_v1", symbol)] = [
            {
                "hot_case_id": f"hotcase-{symbol}",
                "hot_cycle_id": f"hotcycle-{symbol}",
                "symbol": symbol,
                "stock_name": f"STOCK-{symbol}",
                "trade_date": "2026-06-12",
                "decision_time": "2026-06-12T01:25:00Z",
                "lifecycle_stage_at_decision": "auction_confirmed_score",
                "board_count_at_decision": 1,
                "p_limit_up_raw": score,
                "p_limit_up_calibrated": score,
                "case_status": "open",
            }
        ]
        repo.upstream_rows[("decision_hot.hot_score_fact_v1", symbol)] = [
            {
                "score_id": 100,
                "hot_case_id": f"hotcase-{symbol}",
                "score_stage": "auction_confirmed_score",
                "auction_confirmed_score": score,
                "scoring_state": "scored",
                "recommendation_eligibility": "research_only",
                "hard_block_reasons_json": [],
                "warning_reasons_json": [],
            }
        ]
    owner = FakeOwnerClient(mismatched_hot_buy_case=True)
    executor = _executor(repo, owner)

    result = executor.run(
        api_module.ModelExecutionRunRequest(
            task_code="hot.buy_point.open_5m",
            symbol="000063.SZ",
            symbols=["000063.SZ"],
            trade_date=date(2026, 6, 12),
            run_id="scheduler-hot-buy-point",
            extra_context={"scheduler_task_instance_id": "task-hot-buy-point-1"},
        )
    )

    called_symbols = [payload["symbol"] for _, payload in owner.calls]
    cycle_rows = [row for table, row in repo.inserted_rows if table == "decision_hot.hot_cycle_v1"]
    case_rows = [row for table, row in repo.inserted_rows if table == "decision_hot.hot_decision_case_v1"]
    evidence_rows = [row for table, row in repo.inserted_rows if table == "decision_hot.hot_evidence_snapshot_v1"]
    signal_rows = [row for table, row in repo.inserted_rows if table == "decision_hot.hot_signal_fact_v1"]
    buy_rows = [row for table, row in repo.inserted_rows if table == "decision_hot.hot_buy_point_v1"]
    assert result.execution_status == "materialized"
    assert result.symbol is None
    assert result.materialized_counts["fanout_total"] == 2
    assert result.materialized_counts["decision_hot.hot_buy_point_v1"] == 2
    assert "decision_hot.hot_decision_case_v1" not in result.materialized_counts
    assert ("decision_hot.hot_release_gate_audit_v1", "000759.SZ", date(2026, 6, 12)) not in repo.upstream_fetches
    assert called_symbols == ["000759.SZ", "000760.SZ"]
    assert all(symbol != "000063.SZ" for symbol in called_symbols)
    assert cycle_rows == []
    assert case_rows == []
    assert evidence_rows == []
    assert len(signal_rows) == 2
    assert len(buy_rows) == 2
    assert {row["hot_case_id"] for row in signal_rows} == {"hotcase-000759.SZ", "hotcase-000760.SZ"}
    assert {row["hot_case_id"] for row in buy_rows} == {"hotcase-000759.SZ", "hotcase-000760.SZ"}
    assert {row["hot_cycle_id"] for row in signal_rows} == {"hotcycle-000759.SZ", "hotcycle-000760.SZ"}
    assert {row["hot_cycle_id"] for row in buy_rows} == {"hotcycle-000759.SZ", "hotcycle-000760.SZ"}
    assert all(not str(row["hot_signal_id"]).startswith("owner-hotsig-") for row in signal_rows)
    assert all(not str(row["buy_point_id"]).startswith("owner-hotbuy-") for row in buy_rows)
    assert all(row["is_official_signal"] is False for row in signal_rows)
    assert all(row["is_research_only"] is True for row in signal_rows)
    assert all(row["buy_point_status"] == "blocked" for row in buy_rows)
    assert {row["hot_signal_id"] for row in buy_rows} == {row["hot_signal_id"] for row in signal_rows}


def test_hot_signal_release_gate_reason_binds_as_jsonb() -> None:
    bound = ResearchPayloadRepository._bind_value(
        "release_gate_reason",
        ["evidence_available_after_decision_time", "source_preflight_not_passed"],
    )

    assert isinstance(bound, Jsonb)
    assert bound.obj == ["evidence_available_after_decision_time", "source_preflight_not_passed"]


def test_hot_evidence_gap_codes_keep_array_binding() -> None:
    value = ["source_gap:daily_bar_missing"]

    assert ResearchPayloadRepository._bind_value("gap_codes", value) is value


def test_scheduler_hot_score_blocks_when_paid_probability_pool_empty() -> None:
    repo = MemoryRepository()
    repo.source_rows.pop(("source.ths_paid_limit_up_probability_v1", "000759.SZ"))
    repo.source_rows.pop(("source.ths_paid_limit_up_probability_v1", "000760.SZ"))
    owner = FakeOwnerClient()
    executor = _executor(repo, owner)

    result = executor.run(
        api_module.ModelExecutionRunRequest(
            task_code="hot.score.auction_confirmed",
            symbol="000063.SZ",
            trade_date=date(2026, 6, 12),
            extra_context={"scheduler_task_instance_id": "task-hot-score-empty"},
        )
    )

    assert result.execution_status == "blocked_data_gap"
    assert result.accepted is False
    assert result.owner_called is False
    assert "source_gap:hot_score_candidate_pool_empty" in result.gap_codes
    assert owner.calls == []


def test_memory_entity_missing_age_materializes_null_and_blocked_gap() -> None:
    repo = MemoryRepository()
    repo.upstream_rows[("decision_hot.hot_signal_fact_v1", "000759.SZ")] = [
        {
            "hot_signal_id": "hotsig-1",
            "hot_case_id": "hotcase-1",
            "symbol": "000759.SZ",
            "signal_date": "2026-06-12",
            "is_official_signal": True,
            "source_quality_status": "usable",
        }
    ]
    executor = _executor(repo)

    result = executor.run(
        api_module.ModelExecutionRunRequest(
            task_code="memory.seed.from_hot_signals",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )

    entity_rows = [row for table, row in repo.inserted_rows if table == "decision_memory.memory_entity_v1"]
    assert result.execution_status == "materialized_with_gaps"
    assert "source_gap:memory_age_trading_calendar_missing" in result.gap_codes
    assert entity_rows[0]["memory_age_days"] is None
    assert entity_rows[0]["memory_status"] == "blocked_data_gap"
