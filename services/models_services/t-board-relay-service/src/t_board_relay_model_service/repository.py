from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from t_board_relay_model_service.config import FEATURE_VERSION, MODEL_VERSION


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return str(value)


def _parse_date(value: Any) -> date | None:
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


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(jsonable(value))


def _rows_to_json(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [jsonable(dict(row)) for row in rows]


OBSERVATION_COLUMNS: dict[str, tuple[str, ...]] = {
    "day1_candidates": (
        "day1_candidate_pk",
        "day1_candidate_id",
        "canonical_symbol",
        "stock_name",
        "trade_date",
        "candidate_status",
        "is_t_board",
        "float_market_cap_pass",
        "source_gap_codes",
        "created_at",
    ),
    "day2_watch": (
        "day2_watch_pk",
        "day2_watch_snapshot_id",
        "day1_candidate_id",
        "canonical_symbol",
        "day2_trade_date",
        "as_of_time",
        "watch_status",
        "near_limit_flag",
        "distance_to_up_limit_pct",
        "market_context_status",
        "source_gap_codes",
        "created_at",
    ),
    "day2_triggers": (
        "entry_trigger_pk",
        "entry_trigger_id",
        "day1_candidate_id",
        "canonical_symbol",
        "day2_trade_date",
        "trigger_time",
        "entry_trigger_status",
        "not_trigger_reason",
        "order_consumption_side",
        "order_consumption_amount",
        "near_limit_order_absorption_score",
        "relay_consensus_score",
        "source_gap_codes",
        "created_at",
    ),
    "post_entry_status": (
        "post_entry_monitor_pk",
        "post_entry_monitor_id",
        "entry_trigger_id",
        "canonical_symbol",
        "day2_trade_date",
        "post_entry_status",
        "outcome_label",
        "source_gap_codes",
        "created_at",
    ),
    "day3_decisions": (
        "day3_decision_pk",
        "day3_decision_id",
        "entry_trigger_id",
        "canonical_symbol",
        "day3_trade_date",
        "day3_action",
        "source_gap_codes",
        "created_at",
    ),
    "outcomes": (
        "outcome_label_pk",
        "outcome_label_id",
        "entry_trigger_id",
        "day1_candidate_id",
        "canonical_symbol",
        "day1_trade_date",
        "day2_trade_date",
        "day3_trade_date",
        "outcome_label",
        "source_gap_codes",
        "created_at",
    ),
    "game_hypotheses": (
        "game_hypothesis_pk",
        "game_hypothesis_id",
        "canonical_symbol",
        "trade_date",
        "stage",
        "related_entity_id",
        "dominant_capital_intent",
        "game_state_label",
        "confidence_level",
        "created_at",
    ),
    "observation_snapshots": (
        "observation_snapshot_pk",
        "observation_snapshot_id",
        "day1_candidate_id",
        "entry_trigger_id",
        "canonical_symbol",
        "stock_name",
        "trade_date",
        "day_index",
        "as_of_time",
        "captured_at",
        "monitor_interval_minutes",
        "observation_status",
        "current_stage",
        "current_conclusion",
        "key_reason",
        "risk_tip",
        "next_observation",
        "model_score",
        "model_score_label",
        "score_state",
        "model_score_version",
        "relay_strength_label",
        "day1_trade_date",
        "day2_trade_date",
        "day2_trigger_time",
        "day3_trade_date",
        "latest_snapshot_time",
        "last_monitor_at",
        "monitoring_summary",
        "data_gap_count",
        "data_gap_labels",
        "created_at",
    ),
}


class TBoardRelayRepository:
    def __init__(self, database_url: str | None, *, persist_decisions: bool = True) -> None:
        self.database_url = database_url
        self.persist_decisions = persist_decisions

    @property
    def attached(self) -> bool:
        return bool(self.database_url) and self.persist_decisions

    def status(self) -> dict[str, Any]:
        if not self.database_url:
            return {
                "repository_attached": False,
                "database_url_configured": False,
                "warning_codes": ["repository_not_attached_no_database_url"],
            }
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                row = conn.execute("select to_regclass('decision_t_relay.t_board_day1_candidate_v1') as table_regclass").fetchone()
            table_ready = bool(row and row["table_regclass"])
            return {
                "repository_attached": bool(self.persist_decisions and table_ready),
                "database_url_configured": True,
                "persist_decisions": self.persist_decisions,
                "table_ready": table_ready,
                "warning_codes": [] if table_ready else ["repository_not_attached_schema_missing"],
            }
        except Exception as exc:
            return {
                "repository_attached": False,
                "database_url_configured": True,
                "persist_decisions": self.persist_decisions,
                "error": str(exc),
                "warning_codes": ["repository_not_attached_connection_failed"],
            }

    def persist_response(
        self,
        *,
        stage: str,
        request_payload: dict[str, Any],
        response_body: dict[str, Any],
        run_id: str | None,
    ) -> dict[str, Any]:
        status = self.status()
        if not status.get("repository_attached"):
            return {"persisted": False, **status}
        structured = response_body.get("structured_output") or {}
        if stage == "day1_scan":
            return self._persist_day1_scan(structured.get("day1_scan") or {}, request_payload, response_body, run_id)
        if stage == "day2_watch":
            return self._persist_day2_watch(structured.get("day2_watch_snapshot") or {}, request_payload, response_body, run_id)
        if stage == "day2_trigger":
            return self._persist_day2_trigger(structured.get("day2_entry_trigger") or {}, request_payload, response_body, run_id)
        if stage == "post_entry_monitor":
            return self._persist_post_entry_monitor(structured.get("post_entry_monitor") or {}, request_payload, response_body, run_id)
        if stage == "day3_exit":
            return self._persist_day3_exit(structured.get("day3_exit_decision") or {}, request_payload, response_body, run_id)
        if stage == "outcome":
            return self._persist_outcome(structured.get("outcome_label") or {}, request_payload, response_body, run_id)
        return {"persisted": False, "repository_attached": True, "warning_codes": [f"repository_unknown_stage:{stage}"]}

    def _persist_day1_scan(self, scan: dict[str, Any], request_payload: dict[str, Any], response_body: dict[str, Any], run_id: str | None) -> dict[str, Any]:
        candidates = scan.get("candidates") if isinstance(scan.get("candidates"), list) else []
        inserted: list[int] = []
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    row = conn.execute(
                        """
                        insert into decision_t_relay.t_board_day1_candidate_v1 (
                            day1_candidate_id, canonical_symbol, stock_name, trade_date,
                            candidate_status, reject_reason, is_t_board, float_market_cap,
                            float_market_cap_pass, seal_commitment_score,
                            disagreement_absorption_score, fake_seal_trap_risk_score,
                            source_gap_codes, run_id, model_version, feature_version,
                            rule_version, request_payload, result_payload
                        )
                        values (
                            %(day1_candidate_id)s, %(canonical_symbol)s, %(stock_name)s, %(trade_date)s,
                            %(candidate_status)s, %(reject_reason)s, %(is_t_board)s, %(float_market_cap)s,
                            %(float_market_cap_pass)s, %(seal_commitment_score)s,
                            %(disagreement_absorption_score)s, %(fake_seal_trap_risk_score)s,
                            %(source_gap_codes)s, %(run_id)s, %(model_version)s, %(feature_version)s,
                            %(rule_version)s, %(request_payload)s, %(result_payload)s
                        )
                        returning day1_candidate_pk
                        """,
                        {
                            "day1_candidate_id": item.get("day1_candidate_id"),
                            "canonical_symbol": item.get("canonical_symbol"),
                            "stock_name": item.get("stock_name"),
                            "trade_date": _parse_date(item.get("trade_date")),
                            "candidate_status": item.get("candidate_status") or "unknown",
                            "reject_reason": item.get("reject_reason"),
                            "is_t_board": item.get("is_t_board"),
                            "float_market_cap": item.get("float_market_cap"),
                            "float_market_cap_pass": item.get("float_market_cap_pass"),
                            "seal_commitment_score": item.get("seal_commitment_score"),
                            "disagreement_absorption_score": item.get("disagreement_absorption_score"),
                            "fake_seal_trap_risk_score": item.get("fake_seal_trap_risk_score"),
                            "source_gap_codes": _jsonb(item.get("source_gap_codes") or []),
                            "run_id": run_id,
                            "model_version": item.get("model_version") or response_body.get("model_version") or MODEL_VERSION,
                            "feature_version": item.get("feature_version") or FEATURE_VERSION,
                            "rule_version": item.get("rule_version"),
                            "request_payload": _jsonb(request_payload),
                            "result_payload": _jsonb(item),
                        },
                    ).fetchone()
                    inserted.append(int(row["day1_candidate_pk"]))
        return {"persisted": True, "stage": "day1_scan", "inserted_count": len(inserted), "primary_keys": inserted}

    def _persist_day2_watch(self, item: dict[str, Any], request_payload: dict[str, Any], response_body: dict[str, Any], run_id: str | None) -> dict[str, Any]:
        row = self._execute_returning(
            """
            insert into decision_t_relay.t_board_day2_watch_snapshot_v1 (
                day2_watch_snapshot_id, day1_candidate_id, canonical_symbol, day2_trade_date,
                as_of_time, watch_status, near_limit_flag, distance_to_up_limit_pct,
                market_context_status, dynamic_feature_run_id, source_gap_codes,
                run_id, model_version, feature_version, request_payload, result_payload
            )
            values (
                %(day2_watch_snapshot_id)s, %(day1_candidate_id)s, %(canonical_symbol)s, %(day2_trade_date)s,
                %(as_of_time)s, %(watch_status)s, %(near_limit_flag)s, %(distance_to_up_limit_pct)s,
                %(market_context_status)s, %(dynamic_feature_run_id)s, %(source_gap_codes)s,
                %(run_id)s, %(model_version)s, %(feature_version)s, %(request_payload)s, %(result_payload)s
            )
            returning day2_watch_pk
            """,
            {
                "day2_watch_snapshot_id": item.get("day2_watch_snapshot_id"),
                "day1_candidate_id": item.get("day1_candidate_id"),
                "canonical_symbol": item.get("canonical_symbol"),
                "day2_trade_date": _parse_date(item.get("day2_trade_date")),
                "as_of_time": _parse_datetime(item.get("as_of_time")),
                "watch_status": item.get("watch_status") or "unknown",
                "near_limit_flag": item.get("near_limit_flag"),
                "distance_to_up_limit_pct": item.get("distance_to_up_limit_pct"),
                "market_context_status": item.get("market_context_status"),
                "dynamic_feature_run_id": item.get("dynamic_feature_run_id"),
                "source_gap_codes": _jsonb(item.get("source_gap_codes") or []),
                "run_id": run_id,
                "model_version": response_body.get("model_version") or MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "request_payload": _jsonb(request_payload),
                "result_payload": _jsonb(item),
            },
        )
        return {"persisted": True, "stage": "day2_watch", "inserted_count": 1, "primary_keys": [int(row["day2_watch_pk"])]}

    def _persist_day2_trigger(self, item: dict[str, Any], request_payload: dict[str, Any], response_body: dict[str, Any], run_id: str | None) -> dict[str, Any]:
        row = self._execute_returning(
            """
            insert into decision_t_relay.t_board_day2_entry_trigger_v1 (
                entry_trigger_id, day1_candidate_id, canonical_symbol, day2_trade_date,
                trigger_time, entry_trigger_status, not_trigger_reason, near_limit_flag,
                order_consumption_side, order_consumption_amount, near_limit_order_absorption_score,
                relay_consensus_score, market_context_status, dynamic_feature_run_id,
                source_gap_codes, run_id, model_version, feature_version, request_payload,
                result_payload, game_hypothesis_payload
            )
            values (
                %(entry_trigger_id)s, %(day1_candidate_id)s, %(canonical_symbol)s, %(day2_trade_date)s,
                %(trigger_time)s, %(entry_trigger_status)s, %(not_trigger_reason)s, %(near_limit_flag)s,
                %(order_consumption_side)s, %(order_consumption_amount)s, %(near_limit_order_absorption_score)s,
                %(relay_consensus_score)s, %(market_context_status)s, %(dynamic_feature_run_id)s,
                %(source_gap_codes)s, %(run_id)s, %(model_version)s, %(feature_version)s, %(request_payload)s,
                %(result_payload)s, %(game_hypothesis_payload)s
            )
            returning entry_trigger_pk
            """,
            {
                "entry_trigger_id": item.get("entry_trigger_id"),
                "day1_candidate_id": item.get("day1_candidate_id"),
                "canonical_symbol": item.get("canonical_symbol"),
                "day2_trade_date": _parse_date(item.get("day2_trade_date")),
                "trigger_time": item.get("trigger_time"),
                "entry_trigger_status": item.get("entry_trigger_status") or "unknown",
                "not_trigger_reason": item.get("not_trigger_reason"),
                "near_limit_flag": item.get("near_limit_flag"),
                "order_consumption_side": item.get("order_consumption_side"),
                "order_consumption_amount": item.get("order_consumption_amount"),
                "near_limit_order_absorption_score": item.get("near_limit_order_absorption_score"),
                "relay_consensus_score": item.get("relay_consensus_score"),
                "market_context_status": item.get("market_context_status"),
                "dynamic_feature_run_id": item.get("dynamic_feature_run_id"),
                "source_gap_codes": _jsonb(item.get("source_gap_codes") or []),
                "run_id": run_id,
                "model_version": response_body.get("model_version") or MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "request_payload": _jsonb(request_payload),
                "result_payload": _jsonb(item),
                "game_hypothesis_payload": _jsonb(item.get("game_hypothesis") or {}),
            },
        )
        self._persist_game_hypothesis(item.get("game_hypothesis") or {}, item, run_id)
        return {"persisted": True, "stage": "day2_trigger", "inserted_count": 1, "primary_keys": [int(row["entry_trigger_pk"])]}

    def _persist_post_entry_monitor(self, item: dict[str, Any], request_payload: dict[str, Any], response_body: dict[str, Any], run_id: str | None) -> dict[str, Any]:
        row = self._execute_returning(
            """
            insert into decision_t_relay.t_board_post_entry_monitor_v1 (
                post_entry_monitor_id, entry_trigger_id, canonical_symbol, day2_trade_date,
                post_entry_status, outcome_label, post_entry_board_opened,
                close_on_limit_flag, control_failure_score, source_gap_codes,
                run_id, model_version, feature_version, request_payload,
                result_payload, game_hypothesis_payload
            )
            values (
                %(post_entry_monitor_id)s, %(entry_trigger_id)s, %(canonical_symbol)s, %(day2_trade_date)s,
                %(post_entry_status)s, %(outcome_label)s, %(post_entry_board_opened)s,
                %(close_on_limit_flag)s, %(control_failure_score)s, %(source_gap_codes)s,
                %(run_id)s, %(model_version)s, %(feature_version)s, %(request_payload)s,
                %(result_payload)s, %(game_hypothesis_payload)s
            )
            returning post_entry_monitor_pk
            """,
            {
                "post_entry_monitor_id": item.get("post_entry_monitor_id"),
                "entry_trigger_id": item.get("entry_trigger_id"),
                "canonical_symbol": item.get("canonical_symbol"),
                "day2_trade_date": _parse_date(item.get("day2_trade_date")),
                "post_entry_status": item.get("post_entry_status") or "unknown",
                "outcome_label": item.get("outcome_label"),
                "post_entry_board_opened": item.get("post_entry_board_opened"),
                "close_on_limit_flag": item.get("close_on_limit_flag"),
                "control_failure_score": item.get("control_failure_score"),
                "source_gap_codes": _jsonb(item.get("source_gap_codes") or []),
                "run_id": run_id,
                "model_version": response_body.get("model_version") or MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "request_payload": _jsonb(request_payload),
                "result_payload": _jsonb(item),
                "game_hypothesis_payload": _jsonb(item.get("game_hypothesis") or {}),
            },
        )
        self._persist_game_hypothesis(item.get("game_hypothesis") or {}, item, run_id)
        return {"persisted": True, "stage": "post_entry_monitor", "inserted_count": 1, "primary_keys": [int(row["post_entry_monitor_pk"])]}

    def _persist_day3_exit(self, item: dict[str, Any], request_payload: dict[str, Any], response_body: dict[str, Any], run_id: str | None) -> dict[str, Any]:
        row = self._execute_returning(
            """
            insert into decision_t_relay.t_board_day3_exit_decision_v1 (
                day3_decision_id, entry_trigger_id, canonical_symbol, day3_trade_date,
                day3_action, action_reason, day3_open_limit_up_flag, tail_limit_up_flag,
                source_gap_codes, run_id, model_version, feature_version, request_payload,
                result_payload, game_hypothesis_payload
            )
            values (
                %(day3_decision_id)s, %(entry_trigger_id)s, %(canonical_symbol)s, %(day3_trade_date)s,
                %(day3_action)s, %(action_reason)s, %(day3_open_limit_up_flag)s, %(tail_limit_up_flag)s,
                %(source_gap_codes)s, %(run_id)s, %(model_version)s, %(feature_version)s, %(request_payload)s,
                %(result_payload)s, %(game_hypothesis_payload)s
            )
            returning day3_decision_pk
            """,
            {
                "day3_decision_id": item.get("day3_decision_id"),
                "entry_trigger_id": item.get("entry_trigger_id"),
                "canonical_symbol": item.get("canonical_symbol"),
                "day3_trade_date": _parse_date(item.get("day3_trade_date")),
                "day3_action": item.get("day3_action") or "unknown",
                "action_reason": item.get("action_reason"),
                "day3_open_limit_up_flag": item.get("day3_open_limit_up_flag"),
                "tail_limit_up_flag": item.get("tail_limit_up_flag"),
                "source_gap_codes": _jsonb(item.get("source_gap_codes") or []),
                "run_id": run_id,
                "model_version": response_body.get("model_version") or MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "request_payload": _jsonb(request_payload),
                "result_payload": _jsonb(item),
                "game_hypothesis_payload": _jsonb(item.get("game_hypothesis") or {}),
            },
        )
        self._persist_game_hypothesis(item.get("game_hypothesis") or {}, item, run_id)
        return {"persisted": True, "stage": "day3_exit", "inserted_count": 1, "primary_keys": [int(row["day3_decision_pk"])]}

    def _persist_outcome(self, item: dict[str, Any], request_payload: dict[str, Any], response_body: dict[str, Any], run_id: str | None) -> dict[str, Any]:
        row = self._execute_returning(
            """
            insert into decision_t_relay.t_board_outcome_label_v1 (
                outcome_label_id, entry_trigger_id, day1_candidate_id, canonical_symbol,
                day1_trade_date, day2_trade_date, day3_trade_date, outcome_label,
                label_reason, label_version, source_gap_codes, run_id, model_version,
                feature_version, request_payload, result_payload
            )
            values (
                %(outcome_label_id)s, %(entry_trigger_id)s, %(day1_candidate_id)s, %(canonical_symbol)s,
                %(day1_trade_date)s, %(day2_trade_date)s, %(day3_trade_date)s, %(outcome_label)s,
                %(label_reason)s, %(label_version)s, %(source_gap_codes)s, %(run_id)s, %(model_version)s,
                %(feature_version)s, %(request_payload)s, %(result_payload)s
            )
            returning outcome_label_pk
            """,
            {
                "outcome_label_id": item.get("outcome_label_id"),
                "entry_trigger_id": item.get("entry_trigger_id"),
                "day1_candidate_id": item.get("day1_candidate_id"),
                "canonical_symbol": item.get("canonical_symbol"),
                "day1_trade_date": _parse_date(item.get("day1_trade_date")),
                "day2_trade_date": _parse_date(item.get("day2_trade_date")),
                "day3_trade_date": _parse_date(item.get("day3_trade_date")),
                "outcome_label": item.get("outcome_label") or "unknown",
                "label_reason": item.get("label_reason"),
                "label_version": item.get("label_version") or "t_board_outcome_label_v1",
                "source_gap_codes": _jsonb(item.get("source_gap_codes") or []),
                "run_id": run_id,
                "model_version": response_body.get("model_version") or MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "request_payload": _jsonb(request_payload),
                "result_payload": _jsonb(item),
            },
        )
        return {"persisted": True, "stage": "outcome", "inserted_count": 1, "primary_keys": [int(row["outcome_label_pk"])]}

    def _persist_game_hypothesis(self, hypothesis: dict[str, Any], related: dict[str, Any], run_id: str | None) -> None:
        if not hypothesis:
            return
        self._execute_returning(
            """
            insert into decision_t_relay.t_board_game_hypothesis_snapshot_v1 (
                game_hypothesis_id, canonical_symbol, trade_date, stage,
                related_entity_id, dominant_capital_intent, game_state_label,
                confidence_level, evidence_json, related_payload, run_id,
                model_version, feature_version
            )
            values (
                %(game_hypothesis_id)s, %(canonical_symbol)s, %(trade_date)s, %(stage)s,
                %(related_entity_id)s, %(dominant_capital_intent)s, %(game_state_label)s,
                %(confidence_level)s, %(evidence_json)s, %(related_payload)s, %(run_id)s,
                %(model_version)s, %(feature_version)s
            )
            returning game_hypothesis_pk
            """,
            {
                "game_hypothesis_id": hypothesis.get("game_hypothesis_id"),
                "canonical_symbol": hypothesis.get("canonical_symbol"),
                "trade_date": _parse_date(hypothesis.get("trade_date")),
                "stage": hypothesis.get("stage") or "unknown",
                "related_entity_id": hypothesis.get("related_entity_id"),
                "dominant_capital_intent": hypothesis.get("dominant_capital_intent"),
                "game_state_label": hypothesis.get("game_state_label"),
                "confidence_level": hypothesis.get("confidence_level"),
                "evidence_json": _jsonb(hypothesis.get("evidence_json") or {}),
                "related_payload": _jsonb(related),
                "run_id": run_id,
                "model_version": MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
            },
        )

    def persist_observation_monitor_snapshots(
        self,
        *,
        items: list[dict[str, Any]],
        request_payload: dict[str, Any],
        run_id: str | None,
        as_of_time: Any,
        captured_at: Any,
        trade_date: Any,
        monitor_interval_minutes: int,
    ) -> dict[str, Any]:
        status = self.status()
        if not status.get("repository_attached"):
            return {"persisted": False, **status}
        captured_at_dt = _parse_datetime(captured_at) or datetime.now(timezone.utc)
        as_of_time_dt = _parse_datetime(as_of_time) or captured_at_dt
        inserted: list[int] = []
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            table_row = conn.execute(
                "select to_regclass('decision_t_relay.t_board_observation_monitor_snapshot_v1') as table_regclass"
            ).fetchone()
            if not table_row or not table_row["table_regclass"]:
                return {
                    "persisted": False,
                    "repository_attached": True,
                    "warning_codes": ["repository_observation_monitor_snapshot_table_missing"],
                }
            with conn.transaction():
                for item in items:
                    stock = item.get("stock") if isinstance(item.get("stock"), dict) else {}
                    day1_candidate_id = item.get("observation_id") or item.get("day1_candidate_id")
                    symbol = (stock or {}).get("symbol") or item.get("canonical_symbol")
                    snapshot_id = item.get("observation_snapshot_id") or (
                        f"tbr-observation-{day1_candidate_id or symbol}-{captured_at_dt.strftime('%Y%m%d%H%M%S%f')}"
                    )
                    row = conn.execute(
                        """
                        insert into decision_t_relay.t_board_observation_monitor_snapshot_v1 (
                            observation_snapshot_id, day1_candidate_id, entry_trigger_id,
                            canonical_symbol, stock_name, trade_date, day_index, as_of_time,
                            captured_at, monitor_interval_minutes, observation_status,
                            current_stage, current_conclusion, key_reason, risk_tip,
                            next_observation, model_score, model_score_label, score_state,
                            model_score_version, relay_strength_label, day1_trade_date,
                            day2_trade_date, day2_trigger_time, day3_trade_date,
                            latest_snapshot_time, last_monitor_at, monitoring_summary,
                            data_gap_count, data_gap_labels, warning_codes, run_id,
                            model_version, score_version, request_payload, result_payload
                        )
                        values (
                            %(observation_snapshot_id)s, %(day1_candidate_id)s, %(entry_trigger_id)s,
                            %(canonical_symbol)s, %(stock_name)s, %(trade_date)s, %(day_index)s, %(as_of_time)s,
                            %(captured_at)s, %(monitor_interval_minutes)s, %(observation_status)s,
                            %(current_stage)s, %(current_conclusion)s, %(key_reason)s, %(risk_tip)s,
                            %(next_observation)s, %(model_score)s, %(model_score_label)s, %(score_state)s,
                            %(model_score_version)s, %(relay_strength_label)s, %(day1_trade_date)s,
                            %(day2_trade_date)s, %(day2_trigger_time)s, %(day3_trade_date)s,
                            %(latest_snapshot_time)s, %(last_monitor_at)s, %(monitoring_summary)s,
                            %(data_gap_count)s, %(data_gap_labels)s, %(warning_codes)s, %(run_id)s,
                            %(model_version)s, %(score_version)s, %(request_payload)s, %(result_payload)s
                        )
                        returning observation_snapshot_pk
                        """,
                        {
                            "observation_snapshot_id": snapshot_id,
                            "day1_candidate_id": day1_candidate_id,
                            "entry_trigger_id": item.get("entry_trigger_id"),
                            "canonical_symbol": symbol,
                            "stock_name": (stock or {}).get("name") or item.get("stock_name"),
                            "trade_date": _parse_date(item.get("snapshot_trade_date") or trade_date),
                            "day_index": _parse_int(item.get("snapshot_day_index") or item.get("day_index")),
                            "as_of_time": as_of_time_dt,
                            "captured_at": captured_at_dt,
                            "monitor_interval_minutes": _parse_int(item.get("monitor_interval_minutes")) or monitor_interval_minutes,
                            "observation_status": item.get("observation_status") or "unknown",
                            "current_stage": item.get("current_stage"),
                            "current_conclusion": item.get("current_conclusion"),
                            "key_reason": item.get("key_reason"),
                            "risk_tip": item.get("risk_tip"),
                            "next_observation": item.get("next_observation"),
                            "model_score": item.get("model_score"),
                            "model_score_label": item.get("model_score_label"),
                            "score_state": item.get("score_state"),
                            "model_score_version": item.get("model_score_version"),
                            "relay_strength_label": item.get("relay_strength_label"),
                            "day1_trade_date": _parse_date(item.get("day1_trade_date")),
                            "day2_trade_date": _parse_date(item.get("day2_trade_date")),
                            "day2_trigger_time": item.get("day2_trigger_time"),
                            "day3_trade_date": _parse_date(item.get("day3_trade_date")),
                            "latest_snapshot_time": _parse_datetime(item.get("latest_snapshot_time")),
                            "last_monitor_at": str(item.get("last_monitor_at")) if item.get("last_monitor_at") is not None else None,
                            "monitoring_summary": item.get("monitoring_summary"),
                            "data_gap_count": _parse_int(item.get("data_gap_count")) or 0,
                            "data_gap_labels": _jsonb(item.get("data_gap_labels") or []),
                            "warning_codes": _jsonb(item.get("warning_codes") or []),
                            "run_id": run_id,
                            "model_version": item.get("model_version") or MODEL_VERSION,
                            "score_version": item.get("model_score_version"),
                            "request_payload": _jsonb(request_payload),
                            "result_payload": _jsonb(item),
                        },
                    ).fetchone()
                    inserted.append(int(row["observation_snapshot_pk"]))
        return {
            "persisted": True,
            "stage": "observation_monitor_snapshot",
            "inserted_count": len(inserted),
            "primary_keys": inserted,
        }

    def _execute_returning(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                row = conn.execute(sql, params).fetchone()
        return dict(row)

    def list_rows(self, entity: str, *, limit: int = 100) -> list[dict[str, Any]]:
        table, order_column = {
            "day1_candidates": ("decision_t_relay.t_board_day1_candidate_v1", "day1_candidate_pk"),
            "day2_watch": ("decision_t_relay.t_board_day2_watch_snapshot_v1", "day2_watch_pk"),
            "day2_triggers": ("decision_t_relay.t_board_day2_entry_trigger_v1", "entry_trigger_pk"),
            "post_entry_status": ("decision_t_relay.t_board_post_entry_monitor_v1", "post_entry_monitor_pk"),
            "day3_decisions": ("decision_t_relay.t_board_day3_exit_decision_v1", "day3_decision_pk"),
            "outcomes": ("decision_t_relay.t_board_outcome_label_v1", "outcome_label_pk"),
            "game_hypotheses": ("decision_t_relay.t_board_game_hypothesis_snapshot_v1", "game_hypothesis_pk"),
        }[entity]
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(f"select * from {table} order by {order_column} desc limit %(limit)s", {"limit": limit}).fetchall()
        return _rows_to_json([dict(row) for row in rows])

    def list_day1_observation_candidates(self, *, limit: int = 100) -> list[dict[str, Any]]:
        columns = ", ".join(OBSERVATION_COLUMNS["day1_candidates"])
        sql = """
            with latest_day1 as (
                select distinct on (day1_candidate_id) {columns}
                from decision_t_relay.t_board_day1_candidate_v1
                where candidate_status = 'qualified'
                  and is_t_board is true
                  and float_market_cap_pass is true
                order by day1_candidate_id, day1_candidate_pk desc
            )
            select *
            from latest_day1
            order by day1_candidate_pk desc
            limit %(limit)s
        """.format(columns=columns)
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(sql, {"limit": limit}).fetchall()
        return _rows_to_json([dict(row) for row in rows])

    def list_observation_rows(self, entity: str, *, limit: int = 100) -> list[dict[str, Any]]:
        table, order_column = {
            "day2_watch": ("decision_t_relay.t_board_day2_watch_snapshot_v1", "day2_watch_pk"),
            "day2_triggers": ("decision_t_relay.t_board_day2_entry_trigger_v1", "entry_trigger_pk"),
            "post_entry_status": ("decision_t_relay.t_board_post_entry_monitor_v1", "post_entry_monitor_pk"),
            "day3_decisions": ("decision_t_relay.t_board_day3_exit_decision_v1", "day3_decision_pk"),
            "outcomes": ("decision_t_relay.t_board_outcome_label_v1", "outcome_label_pk"),
            "game_hypotheses": ("decision_t_relay.t_board_game_hypothesis_snapshot_v1", "game_hypothesis_pk"),
        }[entity]
        columns = ", ".join(OBSERVATION_COLUMNS[entity])
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                f"select {columns} from {table} order by {order_column} desc limit %(limit)s",
                {"limit": limit},
            ).fetchall()
        return _rows_to_json([dict(row) for row in rows])

    def list_observation_monitor_snapshots(self, *, limit: int = 100) -> list[dict[str, Any]]:
        columns = ", ".join(OBSERVATION_COLUMNS["observation_snapshots"])
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                f"""
                select {columns}
                from decision_t_relay.t_board_observation_monitor_snapshot_v1
                order by observation_snapshot_pk desc
                limit %(limit)s
                """,
                {"limit": limit},
            ).fetchall()
        return _rows_to_json([dict(row) for row in rows])

    def get_by_text_id(self, entity: str, text_id: str) -> dict[str, Any] | None:
        table, id_column, order_column = {
            "day1_candidate": ("decision_t_relay.t_board_day1_candidate_v1", "day1_candidate_id", "day1_candidate_pk"),
            "day2_trigger": ("decision_t_relay.t_board_day2_entry_trigger_v1", "entry_trigger_id", "entry_trigger_pk"),
        }[entity]
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                f"select * from {table} where {id_column} = %(text_id)s order by {order_column} desc limit 1",
                {"text_id": text_id},
            ).fetchone()
        return jsonable(dict(row)) if row else None

    def table_counts(self) -> dict[str, int]:
        tables = {
            "day1_candidates": "decision_t_relay.t_board_day1_candidate_v1",
            "day2_watch_snapshots": "decision_t_relay.t_board_day2_watch_snapshot_v1",
            "day2_triggers": "decision_t_relay.t_board_day2_entry_trigger_v1",
            "post_entry_monitors": "decision_t_relay.t_board_post_entry_monitor_v1",
            "day3_decisions": "decision_t_relay.t_board_day3_exit_decision_v1",
            "outcomes": "decision_t_relay.t_board_outcome_label_v1",
            "game_hypotheses": "decision_t_relay.t_board_game_hypothesis_snapshot_v1",
            "observation_monitor_snapshots": "decision_t_relay.t_board_observation_monitor_snapshot_v1",
            "research_samples": "research_t_relay.t_board_research_sample_v1",
        }
        counts: dict[str, int] = {}
        if not self.database_url:
            return {key: 0 for key in tables}
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            for key, table in tables.items():
                row = conn.execute(f"select count(*) as count from {table}").fetchone()
                counts[key] = int(row["count"])
        return counts
