from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


class MemorySQLiteRepository:
    """Small production-contract repository used by tests and local validation.

    It mirrors the important PostgreSQL semantics for candidate_memory Phase 2:
    - observations are append-only with idempotent primary keys;
    - latest_state is a replaceable projection and never training truth;
    - active registry drives due-case scheduling;
    - repository operations are explicit stage operations rather than one monolithic pipeline.
    """

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(database))
        self.conn.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self.conn.close()

    def initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_active_case_registry_v1 (
              memory_entity_id TEXT PRIMARY KEY,
              symbol TEXT NOT NULL,
              tracking_pool TEXT NOT NULL,
              priority_level INTEGER NOT NULL DEFAULT 0,
              next_observe_at TEXT NOT NULL,
              last_observe_at TEXT,
              observe_frequency_seconds INTEGER NOT NULL,
              memory_status TEXT NOT NULL,
              budget_class TEXT NOT NULL DEFAULT 'normal',
              close_reason TEXT,
              updated_at TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memory_active_due
            ON memory_active_case_registry_v1(memory_status, next_observe_at, priority_level DESC);

            CREATE TABLE IF NOT EXISTS memory_observation_snapshot_v1 (
              observation_id TEXT PRIMARY KEY,
              memory_entity_id TEXT NOT NULL,
              symbol TEXT NOT NULL,
              observe_seq INTEGER NOT NULL,
              observe_time TEXT NOT NULL,
              data_as_of TEXT NOT NULL,
              memory_value_score TEXT,
              pre_signal_score TEXT,
              fake_activation_risk_score TEXT,
              expectation_state TEXT,
              payload_json TEXT NOT NULL,
              UNIQUE(memory_entity_id, observe_seq)
            );

            CREATE TABLE IF NOT EXISTS memory_latest_state_v1 (
              memory_entity_id TEXT PRIMARY KEY,
              symbol TEXT NOT NULL,
              latest_observe_time TEXT,
              memory_status TEXT NOT NULL,
              memory_value_score TEXT,
              pre_signal_score TEXT,
              activation_quality_score TEXT,
              fake_activation_risk_score TEXT,
              latest_state_payload_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_ttl_calibration_v1 (
              calibration_id TEXT PRIMARY KEY,
              model_version TEXT NOT NULL,
              segment_key TEXT NOT NULL,
              mature_sample_count INTEGER NOT NULL,
              current_ttl_days INTEGER NOT NULL,
              suggested_ttl_days INTEGER NOT NULL,
              calibration_state TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: MemorySQLiteRepository._jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [MemorySQLiteRepository._jsonable(item) for item in value]
        return value

    @classmethod
    def _payload(cls, value: dict[str, Any]) -> str:
        return json.dumps(cls._jsonable(value), ensure_ascii=False, sort_keys=True)

    def upsert_registry(self, registry: dict[str, Any]) -> None:
        payload = self._payload(registry)
        self.conn.execute(
            """
            INSERT INTO memory_active_case_registry_v1 (
              memory_entity_id, symbol, tracking_pool, priority_level, next_observe_at, last_observe_at,
              observe_frequency_seconds, memory_status, budget_class, close_reason, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_entity_id) DO UPDATE SET
              symbol=excluded.symbol,
              tracking_pool=excluded.tracking_pool,
              priority_level=excluded.priority_level,
              next_observe_at=excluded.next_observe_at,
              last_observe_at=excluded.last_observe_at,
              observe_frequency_seconds=excluded.observe_frequency_seconds,
              memory_status=excluded.memory_status,
              budget_class=excluded.budget_class,
              close_reason=excluded.close_reason,
              updated_at=excluded.updated_at,
              payload_json=excluded.payload_json
            """,
            (
                registry["memory_entity_id"],
                registry["symbol"],
                registry["tracking_pool"],
                int(registry.get("priority_level") or 0),
                str(registry["next_observe_at"]),
                str(registry.get("last_observe_at")) if registry.get("last_observe_at") else None,
                int(registry["observe_frequency_seconds"]),
                registry["memory_status"],
                registry.get("budget_class") or "normal",
                registry.get("close_reason"),
                str(registry.get("updated_at") or datetime.now(timezone.utc).isoformat()),
                payload,
            ),
        )
        self.conn.commit()

    def get_due_active_cases(self, *, as_of_time_utc: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT payload_json
            FROM memory_active_case_registry_v1
            WHERE memory_status NOT IN ('closed','invalidated','expired_closed')
              AND next_observe_at <= ?
            ORDER BY priority_level DESC, next_observe_at ASC
            LIMIT ?
            """,
            (as_of_time_utc.isoformat(), int(limit)),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def append_observation(self, observation: dict[str, Any]) -> bool:
        payload = self._payload(observation)
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO memory_observation_snapshot_v1 (
              observation_id, memory_entity_id, symbol, observe_seq, observe_time, data_as_of,
              memory_value_score, pre_signal_score, fake_activation_risk_score, expectation_state, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation["observation_id"],
                observation["memory_entity_id"],
                observation["symbol"],
                int(observation["observe_seq"]),
                str(observation["observe_time"]),
                str(observation["data_as_of"]),
                str(observation.get("memory_value_score")) if observation.get("memory_value_score") is not None else None,
                str(observation.get("pre_signal_score")) if observation.get("pre_signal_score") is not None else None,
                str(observation.get("fake_activation_risk_score")) if observation.get("fake_activation_risk_score") is not None else None,
                observation.get("expectation_state"),
                payload,
            ),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def upsert_latest_state(self, latest_state: dict[str, Any]) -> None:
        payload = self._payload(latest_state.get("latest_state_payload") or latest_state)
        self.conn.execute(
            """
            INSERT INTO memory_latest_state_v1 (
              memory_entity_id, symbol, latest_observe_time, memory_status, memory_value_score,
              pre_signal_score, activation_quality_score, fake_activation_risk_score,
              latest_state_payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_entity_id) DO UPDATE SET
              symbol=excluded.symbol,
              latest_observe_time=excluded.latest_observe_time,
              memory_status=excluded.memory_status,
              memory_value_score=excluded.memory_value_score,
              pre_signal_score=excluded.pre_signal_score,
              activation_quality_score=excluded.activation_quality_score,
              fake_activation_risk_score=excluded.fake_activation_risk_score,
              latest_state_payload_json=excluded.latest_state_payload_json,
              updated_at=excluded.updated_at
            """,
            (
                latest_state["memory_entity_id"],
                latest_state["symbol"],
                str(latest_state.get("latest_observe_time")) if latest_state.get("latest_observe_time") else None,
                latest_state.get("memory_status") or "observing",
                str(latest_state.get("memory_value_score")) if latest_state.get("memory_value_score") is not None else None,
                str(latest_state.get("pre_signal_score")) if latest_state.get("pre_signal_score") is not None else None,
                str(latest_state.get("activation_quality_score")) if latest_state.get("activation_quality_score") is not None else None,
                str(latest_state.get("fake_activation_risk_score")) if latest_state.get("fake_activation_risk_score") is not None else None,
                payload,
                str(latest_state.get("updated_at") or datetime.now(timezone.utc).isoformat()),
            ),
        )
        self.conn.commit()

    def apply_bulk_observation_result(self, result: dict[str, Any]) -> dict[str, int]:
        inserted = 0
        ignored = 0
        for observation in result.get("observations") or []:
            if self.append_observation(observation):
                inserted += 1
            else:
                ignored += 1
        for latest_state in result.get("latest_states") or []:
            self.upsert_latest_state(latest_state)
        for registry in result.get("registry_updates") or []:
            self.upsert_registry(registry)
        return {"observations_inserted": inserted, "observations_ignored_duplicate": ignored, "latest_state_upserted": len(result.get("latest_states") or []), "registry_upserted": len(result.get("registry_updates") or [])}

    def save_ttl_calibration(self, report: dict[str, Any]) -> None:
        calibration_id = report.get("calibration_id") or report.get("calibration_hash")
        self.conn.execute(
            """
            INSERT OR REPLACE INTO memory_ttl_calibration_v1 (
              calibration_id, model_version, segment_key, mature_sample_count, current_ttl_days,
              suggested_ttl_days, calibration_state, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                calibration_id,
                report.get("model_version"),
                report.get("segment_key"),
                int(report.get("mature_sample_count") or 0),
                int(report.get("current_ttl_days") or 0),
                int(report.get("suggested_ttl_days") or 0),
                report.get("calibration_state"),
                self._payload(report),
                str(report.get("calibration_cutoff_time") or datetime.now(timezone.utc).isoformat()),
            ),
        )
        self.conn.commit()

    def count_rows(self, table_name: str) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}").fetchone()
        return int(row["cnt"])
