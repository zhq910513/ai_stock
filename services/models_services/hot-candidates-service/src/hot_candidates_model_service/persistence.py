from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = "hot_sqlite_persistence_v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> int:
    return 1 if bool(value) else 0


def _parse_sqlite_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


HOT_SQLITE_DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS hot_cycle_v1 (
    hot_cycle_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    cycle_start_date TEXT,
    cycle_start_reason TEXT,
    latest_lifecycle_stage TEXT NOT NULL,
    max_board_count INTEGER NOT NULL DEFAULT 0,
    primary_theme TEXT,
    primary_catalyst_id TEXT,
    cycle_status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_hot_active_cycle_symbol ON hot_cycle_v1(symbol) WHERE cycle_status = 'active';
CREATE TABLE IF NOT EXISTS hot_cycle_day_feature_v1 (
    feature_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    is_limit_up INTEGER NOT NULL DEFAULT 0,
    is_one_word_limit INTEGER NOT NULL DEFAULT 0,
    is_t_shape_limit INTEGER NOT NULL DEFAULT 0,
    is_opened_limit INTEGER NOT NULL DEFAULT 0,
    board_count INTEGER NOT NULL DEFAULT 0,
    consecutive_board_count INTEGER NOT NULL DEFAULT 0,
    break_board_flag INTEGER NOT NULL DEFAULT 0,
    relimit_after_break_flag INTEGER NOT NULL DEFAULT 0,
    turnover_rate REAL,
    volume_ratio REAL,
    seal_amount REAL,
    seal_strength_score REAL,
    opened_times INTEGER,
    intraday_fade_score REAL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL,
    calculated_at TEXT NOT NULL,
    feature_hash TEXT NOT NULL,
    UNIQUE(symbol, trade_date)
);
CREATE TABLE IF NOT EXISTS hot_intraday_feature_snapshot_v1 (
    feature_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    snapshot_time TEXT NOT NULL,
    latest_price REAL,
    vwap_state TEXT,
    intraday_drawdown_pct REAL,
    volume_ratio REAL,
    moneyflow_state TEXT,
    sector_state TEXT,
    market_state TEXT,
    calculated_at TEXT NOT NULL,
    feature_hash TEXT NOT NULL,
    UNIQUE(symbol, snapshot_time)
);
CREATE TABLE IF NOT EXISTS hot_execution_feature_snapshot_v1 (
    feature_id TEXT PRIMARY KEY,
    hot_case_id TEXT,
    symbol TEXT NOT NULL,
    calc_stage TEXT NOT NULL,
    auction_price REAL,
    auction_matched_amount REAL,
    auction_imbalance_ratio REAL,
    open_5m_vwap REAL,
    entry_vs_vwap_deviation_pct REAL,
    open_gap_pct REAL,
    open_overheat_score REAL,
    no_fill_risk_score REAL,
    calculated_at TEXT NOT NULL,
    feature_hash TEXT NOT NULL,
    UNIQUE(hot_case_id, calc_stage)
);
CREATE TABLE IF NOT EXISTS hot_active_case_registry_v1 (
    hot_case_id TEXT PRIMARY KEY,
    hot_cycle_id TEXT NOT NULL,
    tracking_pool TEXT NOT NULL,
    priority_level INTEGER NOT NULL DEFAULT 0,
    next_observe_at TEXT NOT NULL,
    last_observe_at TEXT,
    observe_frequency_seconds INTEGER NOT NULL DEFAULT 300,
    case_status TEXT NOT NULL DEFAULT 'active',
    close_reason TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id),
    FOREIGN KEY(hot_cycle_id) REFERENCES hot_cycle_v1(hot_cycle_id)
);
CREATE INDEX IF NOT EXISTS idx_hot_active_due ON hot_active_case_registry_v1(case_status, next_observe_at, priority_level DESC);
CREATE TABLE IF NOT EXISTS hot_case_latest_state_v1 (
    hot_case_id TEXT PRIMARY KEY,
    hot_cycle_id TEXT NOT NULL,
    latest_observation_id TEXT,
    latest_price REAL,
    return_from_reference_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    first_event_type TEXT,
    expectation_state TEXT,
    freshness_status TEXT,
    quality_status TEXT,
    monitoring_status TEXT NOT NULL DEFAULT 'monitoring',
    sequence_no INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id)
);
CREATE TABLE IF NOT EXISTS hot_calibration_job_v1 (
    calibration_job_id TEXT PRIMARY KEY,
    calibration_version TEXT NOT NULL,
    training_window_start TEXT NOT NULL,
    training_window_end TEXT NOT NULL,
    calibration_cutoff_time TEXT NOT NULL,
    raw_sample_count INTEGER NOT NULL,
    mature_sample_count INTEGER NOT NULL,
    can_activate INTEGER NOT NULL DEFAULT 0,
    activation_status TEXT NOT NULL,
    report_json TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hot_teacher_calibration_version_v1 (
    calibration_version TEXT PRIMARY KEY,
    training_window_start TEXT NOT NULL,
    training_window_end TEXT NOT NULL,
    calibration_cutoff_time TEXT NOT NULL,
    mature_sample_count INTEGER NOT NULL,
    min_total_samples INTEGER NOT NULL,
    activation_status TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    activated_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hot_candidate_model_version_v1 (
    candidate_model_version TEXT PRIMARY KEY,
    base_model_version TEXT NOT NULL,
    candidate_reason TEXT NOT NULL,
    generated_from_calibration_version TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hot_shadow_run_result_v1 (
    shadow_run_id TEXT PRIMARY KEY,
    candidate_model_version TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    direction_success_rate REAL,
    execution_success_rate REAL,
    avg_mfe_pct REAL,
    avg_mae_pct REAL,
    validation_status TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hot_decision_case_v1 (
    hot_case_id TEXT PRIMARY KEY,
    hot_cycle_id TEXT NOT NULL,
    batch_id TEXT,
    candidate_id TEXT,
    instrument_id TEXT,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    trade_date TEXT,
    decision_time TEXT NOT NULL,
    lifecycle_stage_at_decision TEXT NOT NULL,
    board_count_at_decision INTEGER NOT NULL DEFAULT 0,
    p_limit_up_raw REAL,
    p_limit_up_calibrated REAL,
    case_status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(batch_id, candidate_id, trade_date),
    FOREIGN KEY(hot_cycle_id) REFERENCES hot_cycle_v1(hot_cycle_id)
);
CREATE TABLE IF NOT EXISTS hot_initial_decision_snapshot_v1 (
    initial_snapshot_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL UNIQUE,
    hot_cycle_id TEXT NOT NULL,
    decision_time TEXT NOT NULL,
    model_version TEXT NOT NULL,
    first_score REAL,
    first_lifecycle_stage TEXT NOT NULL,
    first_teacher_prior_raw REAL,
    first_teacher_prior_calibrated REAL,
    first_release_gate_status TEXT NOT NULL,
    is_immutable_first_decision INTEGER NOT NULL DEFAULT 1,
    positive_factors_json TEXT NOT NULL DEFAULT '[]',
    negative_factors_json TEXT NOT NULL DEFAULT '[]',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id),
    FOREIGN KEY(hot_cycle_id) REFERENCES hot_cycle_v1(hot_cycle_id)
);
CREATE TABLE IF NOT EXISTS hot_score_fact_v1 (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hot_case_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    score_stage TEXT NOT NULL,
    pre_auction_score REAL,
    auction_confirmed_score REAL,
    open_5m_confirmed_score REAL,
    official_hot_score REAL,
    scoring_state TEXT NOT NULL,
    recommendation_eligibility TEXT NOT NULL,
    score_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id)
);
CREATE TABLE IF NOT EXISTS hot_release_gate_audit_v1 (
    release_gate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hot_case_id TEXT NOT NULL,
    gate_version TEXT NOT NULL,
    gate_time TEXT NOT NULL,
    gate_status TEXT NOT NULL,
    official_signal_allowed INTEGER NOT NULL DEFAULT 0,
    signal_stage TEXT NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    release_gate_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id)
);
CREATE TABLE IF NOT EXISTS hot_signal_fact_v1 (
    hot_signal_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL,
    hot_cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal_date TEXT,
    selected_at TEXT NOT NULL,
    decision_time TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_score REAL,
    signal_stage TEXT NOT NULL,
    is_official_signal INTEGER NOT NULL DEFAULT 0,
    is_research_only INTEGER NOT NULL DEFAULT 1,
    release_gate_status TEXT NOT NULL,
    release_gate_reason TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id),
    FOREIGN KEY(hot_cycle_id) REFERENCES hot_cycle_v1(hot_cycle_id)
);
CREATE TABLE IF NOT EXISTS hot_buy_point_v1 (
    buy_point_id TEXT PRIMARY KEY,
    hot_signal_id TEXT NOT NULL,
    hot_case_id TEXT NOT NULL,
    hot_cycle_id TEXT NOT NULL,
    adapter_code TEXT NOT NULL,
    buy_point_version TEXT NOT NULL,
    calc_stage TEXT NOT NULL,
    reference_entry_price REAL,
    entry_price_low REAL,
    entry_price_high REAL,
    target_price REAL,
    invalidation_price REAL,
    risk_reward_ratio REAL,
    buy_point_status TEXT NOT NULL,
    block_reason TEXT,
    calculated_at TEXT NOT NULL,
    data_as_of TEXT NOT NULL,
    is_first_valid INTEGER NOT NULL DEFAULT 0,
    is_frozen_reference INTEGER NOT NULL DEFAULT 0,
    decision_trace_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_signal_id) REFERENCES hot_signal_fact_v1(hot_signal_id),
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id),
    FOREIGN KEY(hot_cycle_id) REFERENCES hot_cycle_v1(hot_cycle_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hot_first_frozen_reference ON hot_buy_point_v1(hot_signal_id) WHERE is_frozen_reference = 1;
CREATE TABLE IF NOT EXISTS hot_observation_snapshot_v1 (
    observation_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL,
    hot_cycle_id TEXT NOT NULL,
    observe_seq INTEGER NOT NULL,
    observe_time TEXT NOT NULL,
    data_as_of TEXT NOT NULL,
    observe_stage TEXT NOT NULL,
    latest_price REAL,
    reference_entry_price REAL,
    return_from_reference_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    first_event_type TEXT,
    expectation_state TEXT NOT NULL,
    deviation_reason_codes TEXT NOT NULL DEFAULT '[]',
    support_strength_score REAL,
    contradiction_score REAL,
    freshness_status TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    sequence_no INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id),
    FOREIGN KEY(hot_cycle_id) REFERENCES hot_cycle_v1(hot_cycle_id),
    UNIQUE(hot_case_id, observe_seq)
);
CREATE TABLE IF NOT EXISTS hot_outcome_label_v1 (
    outcome_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL UNIQUE,
    label_version TEXT NOT NULL,
    direction_outcome TEXT NOT NULL,
    execution_outcome TEXT NOT NULL,
    path_outcome TEXT,
    environment_outcome TEXT,
    data_outcome TEXT,
    validation_status TEXT NOT NULL,
    t5_status TEXT,
    t20_status TEXT,
    first_target_hit_at TEXT,
    first_invalidation_hit_at TEXT,
    first_event_type TEXT,
    actual_days_to_target INTEGER,
    mfe_pct REAL,
    mae_pct REAL,
    max_return_pct REAL,
    max_drawdown_pct REAL,
    relative_market_return_pct REAL,
    relative_sector_return_pct REAL,
    label_maturity_status TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id)
);
CREATE TABLE IF NOT EXISTS hot_failure_attribution_v1 (
    failure_attribution_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL,
    failure_causality_type TEXT NOT NULL,
    primary_failure_reason TEXT NOT NULL,
    secondary_failure_reasons_json TEXT NOT NULL DEFAULT '[]',
    similar_case_bucket TEXT,
    similar_case_count INTEGER,
    similar_case_failure_rate_pct REAL,
    is_systematic_pattern INTEGER NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id)
);
CREATE TABLE IF NOT EXISTS hot_first_output_distortion_analysis_v1 (
    distortion_analysis_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL,
    first_model_version TEXT NOT NULL,
    first_score REAL,
    first_lifecycle_stage TEXT,
    first_teacher_prior_raw REAL,
    first_teacher_prior_calibrated REAL,
    final_outcome TEXT,
    distortion_type TEXT NOT NULL,
    primary_distortion_factor TEXT,
    secondary_distortion_factors TEXT NOT NULL DEFAULT '[]',
    is_systematic_pattern INTEGER NOT NULL DEFAULT 0,
    recommended_correction TEXT NOT NULL DEFAULT '{}',
    analysis_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id)
);
CREATE TABLE IF NOT EXISTS hot_evolution_sample_v1 (
    evolution_sample_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL,
    hot_cycle_id TEXT NOT NULL,
    source_observation_id TEXT,
    sample_type TEXT NOT NULL,
    lifecycle_stage_at_decision TEXT,
    outcome_label TEXT,
    execution_label TEXT,
    failure_reason TEXT,
    correction_direction TEXT,
    recommended_adjustment_json TEXT NOT NULL DEFAULT '{}',
    sample_weight REAL NOT NULL DEFAULT 1,
    maturity_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id),
    FOREIGN KEY(hot_cycle_id) REFERENCES hot_cycle_v1(hot_cycle_id)
);
CREATE TABLE IF NOT EXISTS hot_research_sample_pool_v1 (
    pool_record_id TEXT PRIMARY KEY,
    hot_case_id TEXT NOT NULL,
    hot_cycle_id TEXT,
    symbol TEXT,
    trade_date TEXT,
    lifecycle_stage TEXT,
    probability_bucket TEXT,
    teacher_prior_raw REAL,
    official_hot_score REAL,
    release_gate_status TEXT,
    signal_stage TEXT,
    tracking_pool TEXT NOT NULL,
    should_track INTEGER NOT NULL DEFAULT 1,
    tracking_frequency_hint TEXT,
    tracking_reason_codes_json TEXT NOT NULL DEFAULT '[]',
    include_in_official_success_rate INTEGER NOT NULL DEFAULT 0,
    include_in_teacher_calibration INTEGER NOT NULL DEFAULT 0,
    include_in_model_evolution INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL,
    FOREIGN KEY(hot_case_id) REFERENCES hot_decision_case_v1(hot_case_id)
);
CREATE TABLE IF NOT EXISTS hot_teacher_calibration_v1 (
    calibration_row_id TEXT PRIMARY KEY,
    calibration_version TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    probability_bucket TEXT NOT NULL,
    market_regime_bucket TEXT NOT NULL DEFAULT 'all',
    sector_heat_bucket TEXT NOT NULL DEFAULT 'all',
    sample_count INTEGER NOT NULL,
    evaluated_count INTEGER NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    realized_hit_rate REAL,
    avg_predicted_probability REAL,
    calibration_error REAL,
    brier_score REAL,
    lift_vs_overall REAL,
    can_activate INTEGER NOT NULL DEFAULT 0,
    recommended_action TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    UNIQUE(calibration_version, lifecycle_stage, probability_bucket, market_regime_bucket, sector_heat_bucket)
);
CREATE TABLE IF NOT EXISTS hot_model_version_evaluation_v1 (
    model_version_evaluation_id TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    official_signal_count INTEGER NOT NULL,
    direction_success_rate REAL,
    execution_success_rate REAL,
    avg_mfe_pct REAL,
    avg_mae_pct REAL,
    systematic_failure_json TEXT NOT NULL DEFAULT '[]',
    version_status TEXT NOT NULL DEFAULT 'candidate',
    generated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class PersistenceSummary:
    contract_kind: str
    schema_version: str
    hot_case_id: str
    hot_cycle_id: str
    hot_signal_id: str
    inserted_observation_count: int
    table_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_kind": self.contract_kind,
            "schema_version": self.schema_version,
            "hot_case_id": self.hot_case_id,
            "hot_cycle_id": self.hot_cycle_id,
            "hot_signal_id": self.hot_signal_id,
            "inserted_observation_count": self.inserted_observation_count,
            "table_counts": self.table_counts,
        }


class HotSQLitePersistence:
    """Portable real persistence for local validation.

    Production Postgres uses infra/sql DDL. This SQLite store deliberately mirrors the
    decision_hot lifecycle tables so tests can execute an actual write/read path without
    Docker or a running database.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(HOT_SQLITE_DDL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def table_count(self, table: str) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def latest_initial_snapshot(self, hot_case_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM hot_initial_decision_snapshot_v1 WHERE hot_case_id = ?", (hot_case_id,)
        ).fetchone()
        return dict(row) if row else None

    def apply_pipeline(self, pipeline: dict[str, Any]) -> PersistenceSummary:
        research = pipeline["research_contract"]
        cycle = research["hot_cycle"]
        case = research["hot_decision_case"]
        teacher = research.get("teacher_calibration") or {}
        initial = research["initial_decision_snapshot"]
        stage_scores = research["stage_scores"]
        release_gate = research["release_gate"]
        signal = pipeline["hot_signal"]
        buy_point = pipeline["buy_point"]
        observations = list(pipeline.get("observations") or [])
        outcome = pipeline["outcome_label"]
        failure = pipeline["failure_attribution"]
        distortion = pipeline["first_output_distortion_analysis"]
        evolution = pipeline["evolution_sample"]
        research_pool = pipeline.get("research_sample_pool") or {}
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO hot_cycle_v1 (hot_cycle_id, symbol, stock_name, cycle_start_date, cycle_start_reason,
                    latest_lifecycle_stage, max_board_count, primary_theme, primary_catalyst_id, cycle_status,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(hot_cycle_id) DO UPDATE SET
                    latest_lifecycle_stage=excluded.latest_lifecycle_stage,
                    max_board_count=MAX(hot_cycle_v1.max_board_count, excluded.max_board_count),
                    updated_at=excluded.updated_at
                """,
                (
                    cycle["hot_cycle_id"], cycle["symbol"], cycle.get("stock_name"), cycle.get("cycle_start_date"),
                    cycle.get("cycle_start_reason"), cycle.get("lifecycle_stage"), cycle.get("board_count") or 0,
                    cycle.get("primary_theme"), cycle.get("primary_catalyst_id"), now, now,
                ),
            )
            conn.execute(
                """
                INSERT INTO hot_decision_case_v1 (hot_case_id, hot_cycle_id, batch_id, candidate_id, instrument_id,
                    symbol, stock_name, trade_date, decision_time, lifecycle_stage_at_decision,
                    board_count_at_decision, p_limit_up_raw, p_limit_up_calibrated, case_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                ON CONFLICT(hot_case_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (
                    case["hot_case_id"], case["hot_cycle_id"], _text(case.get("batch_id")), _text(case.get("candidate_id")),
                    _text(case.get("instrument_id")), case["symbol"], case.get("stock_name"), case.get("trade_date"),
                    _text(case.get("decision_time")), case.get("lifecycle_stage_at_decision"), case.get("board_count_at_decision") or 0,
                    _num(teacher.get("teacher_prior_raw")), _num(teacher.get("teacher_prior_calibrated")), now, now,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO hot_initial_decision_snapshot_v1 (initial_snapshot_id, hot_case_id, hot_cycle_id,
                    decision_time, model_version, first_score, first_lifecycle_stage, first_teacher_prior_raw,
                    first_teacher_prior_calibrated, first_release_gate_status, is_immutable_first_decision,
                    positive_factors_json, negative_factors_json, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    initial["initial_snapshot_id"], initial["hot_case_id"], initial["hot_cycle_id"], _text(initial.get("decision_time")),
                    initial.get("model_version"), _num(initial.get("first_score")), initial.get("first_lifecycle_stage"),
                    _num(initial.get("first_teacher_prior_raw")), _num(initial.get("first_teacher_prior_calibrated")),
                    initial.get("first_release_gate_status"), _json(initial.get("positive_factors") or []),
                    _json(initial.get("negative_factors") or []), _json(initial), now,
                ),
            )
            conn.execute(
                """
                INSERT INTO hot_score_fact_v1 (hot_case_id, model_version, score_stage, pre_auction_score,
                    auction_confirmed_score, open_5m_confirmed_score, official_hot_score, scoring_state,
                    recommendation_eligibility, score_json, created_at)
                VALUES (?, ?, 'official', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case["hot_case_id"], stage_scores.get("score_model_version") or pipeline.get("model_version"),
                    _num(stage_scores.get("pre_auction_score")), _num(stage_scores.get("auction_confirmed_score")),
                    _num(stage_scores.get("open_5m_confirmed_score")), _num(stage_scores.get("official_hot_score")),
                    "scored" if stage_scores.get("official_hot_score") is not None else "score_incomplete",
                    release_gate.get("recommendation_eligibility"), _json(stage_scores), now,
                ),
            )
            conn.execute(
                """
                INSERT INTO hot_release_gate_audit_v1 (hot_case_id, gate_version, gate_time, gate_status,
                    official_signal_allowed, signal_stage, reasons_json, release_gate_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case["hot_case_id"], release_gate.get("gate_version"), _text(case.get("decision_time")),
                    release_gate.get("gate_status"), _bool(release_gate.get("official_signal_allowed")),
                    release_gate.get("signal_stage"), _json((release_gate.get("block_reasons") or []) + (release_gate.get("warning_reasons") or [])),
                    _json(release_gate), now,
                ),
            )
            conn.execute(
                """
                INSERT INTO hot_signal_fact_v1 (hot_signal_id, hot_case_id, hot_cycle_id, symbol, signal_date,
                    selected_at, decision_time, model_version, model_score, signal_stage, is_official_signal,
                    is_research_only, release_gate_status, release_gate_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hot_signal_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (
                    signal["hot_signal_id"], signal["hot_case_id"], signal["hot_cycle_id"], signal["symbol"], signal.get("signal_date"),
                    _text(signal.get("selected_at")), _text(signal.get("decision_time")), signal.get("model_version"),
                    _num(signal.get("model_score")), signal.get("signal_stage"), _bool(signal.get("is_official_signal")),
                    _bool(signal.get("is_research_only")), signal.get("release_gate_status"), _json(signal.get("release_gate_reason") or []), now, now,
                ),
            )
            if buy_point.get("buy_point_id"):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO hot_buy_point_v1 (buy_point_id, hot_signal_id, hot_case_id, hot_cycle_id,
                        adapter_code, buy_point_version, calc_stage, reference_entry_price, entry_price_low,
                        entry_price_high, target_price, invalidation_price, risk_reward_ratio, buy_point_status,
                        block_reason, calculated_at, data_as_of, is_first_valid, is_frozen_reference,
                        decision_trace_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        buy_point["buy_point_id"], buy_point.get("hot_signal_id") or signal["hot_signal_id"], buy_point["hot_case_id"],
                        buy_point["hot_cycle_id"], buy_point.get("adapter_code"), buy_point.get("adapter_version"), buy_point.get("calc_stage"),
                        _num(buy_point.get("reference_entry_price")), _num(buy_point.get("entry_price_low")), _num(buy_point.get("entry_price_high")),
                        _num(buy_point.get("target_price")), _num(buy_point.get("invalidation_price")), _num(buy_point.get("risk_reward_ratio")),
                        buy_point.get("buy_point_status"), buy_point.get("block_reason"), _text(buy_point.get("calculated_at")),
                        _text(buy_point.get("data_as_of")), _bool(buy_point.get("is_first_valid")), _bool(buy_point.get("is_frozen_reference")),
                        _json(buy_point.get("decision_trace_json") or {}), now,
                    ),
                )
            inserted_observations = 0
            for obs in observations:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO hot_observation_snapshot_v1 (observation_id, hot_case_id, hot_cycle_id,
                        observe_seq, observe_time, data_as_of, observe_stage, latest_price, reference_entry_price,
                        return_from_reference_pct, mfe_pct, mae_pct, first_event_type, expectation_state,
                        deviation_reason_codes, support_strength_score, contradiction_score, freshness_status,
                        quality_status, sequence_no, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obs["observation_id"], obs["hot_case_id"], obs["hot_cycle_id"], int(obs.get("observe_seq") or 0),
                        _text(obs.get("observe_time")), _text(obs.get("data_as_of")), obs.get("observe_stage"),
                        _num(obs.get("latest_price")), _num(obs.get("reference_entry_price")), _num(obs.get("return_from_reference_pct")),
                        _num(obs.get("mfe_pct")), _num(obs.get("mae_pct")), obs.get("first_event_type"), obs.get("expectation_state"),
                        _json(obs.get("deviation_reason_codes") or []), _num(obs.get("support_strength_score")),
                        _num(obs.get("contradiction_score")), obs.get("freshness_status"), obs.get("quality_status"),
                        int(obs.get("sequence_no") or obs.get("observe_seq") or 0), now,
                    ),
                )
                if conn.total_changes:
                    inserted_observations += 1
            conn.execute(
                """
                INSERT INTO hot_outcome_label_v1 (outcome_id, hot_case_id, label_version, direction_outcome,
                    execution_outcome, path_outcome, environment_outcome, data_outcome, validation_status,
                    t5_status, t20_status, first_target_hit_at, first_invalidation_hit_at, first_event_type,
                    actual_days_to_target, mfe_pct, mae_pct, max_return_pct, max_drawdown_pct,
                    relative_market_return_pct, relative_sector_return_pct, label_maturity_status, outcome_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hot_case_id) DO UPDATE SET
                    direction_outcome=excluded.direction_outcome,
                    execution_outcome=excluded.execution_outcome,
                    path_outcome=excluded.path_outcome,
                    validation_status=excluded.validation_status,
                    t5_status=excluded.t5_status,
                    t20_status=excluded.t20_status,
                    first_target_hit_at=excluded.first_target_hit_at,
                    first_invalidation_hit_at=excluded.first_invalidation_hit_at,
                    first_event_type=excluded.first_event_type,
                    actual_days_to_target=excluded.actual_days_to_target,
                    mfe_pct=excluded.mfe_pct,
                    mae_pct=excluded.mae_pct,
                    max_return_pct=excluded.max_return_pct,
                    max_drawdown_pct=excluded.max_drawdown_pct,
                    label_maturity_status=excluded.label_maturity_status,
                    outcome_json=excluded.outcome_json,
                    updated_at=excluded.updated_at
                """,
                (
                    outcome["outcome_id"], outcome["hot_case_id"], outcome.get("label_version"), outcome.get("direction_outcome"),
                    outcome.get("execution_outcome"), outcome.get("path_outcome"), outcome.get("environment_outcome"), outcome.get("data_outcome"),
                    outcome.get("validation_status"), outcome.get("t5_status"), outcome.get("t20_status"), _text(outcome.get("first_target_hit_at")),
                    _text(outcome.get("first_invalidation_hit_at")), outcome.get("first_event_type"), outcome.get("actual_days_to_target"),
                    _num(outcome.get("mfe_pct")), _num(outcome.get("mae_pct")), _num(outcome.get("max_return_pct")),
                    _num(outcome.get("max_drawdown_pct")), _num(outcome.get("relative_market_return_pct")),
                    _num(outcome.get("relative_sector_return_pct")), outcome.get("label_maturity_status"), _json(outcome), now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO hot_failure_attribution_v1 (failure_attribution_id, hot_case_id,
                    failure_causality_type, primary_failure_reason, secondary_failure_reasons_json,
                    similar_case_bucket, similar_case_count, similar_case_failure_rate_pct, is_systematic_pattern,
                    evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    failure["failure_attribution_id"], failure["hot_case_id"], failure.get("failure_causality_type"),
                    failure.get("primary_failure_reason"), _json(failure.get("secondary_failure_reasons") or []),
                    failure.get("similar_case_bucket"), failure.get("similar_case_count"), _num(failure.get("similar_case_failure_rate_pct")),
                    _bool(failure.get("is_systematic_pattern")), _json(failure.get("evidence_json") or {}), now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO hot_first_output_distortion_analysis_v1 (distortion_analysis_id, hot_case_id,
                    first_model_version, first_score, first_lifecycle_stage, first_teacher_prior_raw,
                    first_teacher_prior_calibrated, final_outcome, distortion_type, primary_distortion_factor,
                    secondary_distortion_factors, is_systematic_pattern, recommended_correction, analysis_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    distortion["distortion_analysis_id"], distortion.get("hot_case_id"), distortion.get("first_model_version"),
                    _num(distortion.get("first_score")), distortion.get("first_lifecycle_stage"), _num(distortion.get("first_teacher_prior_raw")),
                    _num(distortion.get("first_teacher_prior_calibrated")), distortion.get("final_outcome"), distortion.get("distortion_type"),
                    distortion.get("primary_distortion_factor"), _json(distortion.get("secondary_distortion_factors") or []),
                    _bool(distortion.get("is_systematic_pattern")), _json(distortion.get("recommended_correction") or {}),
                    distortion.get("analysis_status"), now,
                ),
            )
            if evolution.get("evolution_sample_id"):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO hot_evolution_sample_v1 (evolution_sample_id, hot_case_id, hot_cycle_id,
                        source_observation_id, sample_type, lifecycle_stage_at_decision, outcome_label, execution_label,
                        failure_reason, correction_direction, recommended_adjustment_json, sample_weight, maturity_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evolution["evolution_sample_id"], evolution.get("hot_case_id"), evolution.get("hot_cycle_id"),
                        evolution.get("source_observation_id"), evolution.get("sample_type"), evolution.get("lifecycle_stage_at_decision"),
                        evolution.get("outcome_label"), evolution.get("execution_label"), evolution.get("failure_reason"),
                        evolution.get("correction_direction"), _json(evolution.get("recommended_adjustment_json") or {}),
                        _num(evolution.get("sample_weight")) or 1.0, evolution.get("maturity_status"), now,
                    ),
                )
            if research_pool.get("pool_record_id"):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO hot_research_sample_pool_v1 (pool_record_id, hot_case_id, hot_cycle_id, symbol,
                        trade_date, lifecycle_stage, probability_bucket, teacher_prior_raw, official_hot_score,
                        release_gate_status, signal_stage, tracking_pool, should_track, tracking_frequency_hint,
                        tracking_reason_codes_json, include_in_official_success_rate, include_in_teacher_calibration,
                        include_in_model_evolution, generated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        research_pool["pool_record_id"], research_pool.get("hot_case_id"), research_pool.get("hot_cycle_id"),
                        research_pool.get("symbol"), research_pool.get("trade_date"), research_pool.get("lifecycle_stage"),
                        research_pool.get("probability_bucket"), _num(research_pool.get("teacher_prior_raw")),
                        _num(research_pool.get("official_hot_score")), research_pool.get("release_gate_status"),
                        research_pool.get("signal_stage"), research_pool.get("tracking_pool"), _bool(research_pool.get("should_track")),
                        research_pool.get("tracking_frequency_hint"), _json(research_pool.get("tracking_reason_codes") or []),
                        _bool(research_pool.get("include_in_official_success_rate")),
                        _bool(research_pool.get("include_in_teacher_calibration")),
                        _bool(research_pool.get("include_in_model_evolution")), _text(research_pool.get("generated_at")) or now,
                    ),
                )
        tables = [
            "hot_cycle_v1", "hot_decision_case_v1", "hot_initial_decision_snapshot_v1", "hot_signal_fact_v1",
            "hot_buy_point_v1", "hot_observation_snapshot_v1", "hot_outcome_label_v1",
            "hot_failure_attribution_v1", "hot_first_output_distortion_analysis_v1", "hot_evolution_sample_v1",
            "hot_research_sample_pool_v1",
        ]
        return PersistenceSummary(
            contract_kind="hot_pipeline_persistence_summary_v1",
            schema_version=SCHEMA_VERSION,
            hot_case_id=case["hot_case_id"],
            hot_cycle_id=cycle["hot_cycle_id"],
            hot_signal_id=signal["hot_signal_id"],
            inserted_observation_count=len(observations),
            table_counts={table: self.table_count(table) for table in tables},
        )


    def apply_feature_snapshots(self, features: list[dict[str, Any]]) -> int:
        """Persist precomputed hot features. These tables are read by model stages so
        high-volume source facts do not need to be rescanned per case."""
        inserted = 0
        with self.transaction() as conn:
            for item in features:
                feature_type = item.get("feature_type")
                if feature_type == "hot_cycle_day_feature_v1":
                    before = conn.total_changes
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO hot_cycle_day_feature_v1 (feature_id, symbol, trade_date, is_limit_up,
                            is_one_word_limit, is_t_shape_limit, is_opened_limit, board_count, consecutive_board_count,
                            break_board_flag, relimit_after_break_flag, turnover_rate, volume_ratio, seal_amount,
                            seal_strength_score, opened_times, intraday_fade_score, open_price, high_price, low_price,
                            close_price, calculated_at, feature_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["feature_id"], item["symbol"], item["trade_date"], _bool(item.get("is_limit_up")),
                            _bool(item.get("is_one_word_limit")), _bool(item.get("is_t_shape_limit")),
                            _bool(item.get("is_opened_limit")), int(item.get("board_count") or 0),
                            int(item.get("consecutive_board_count") or 0), _bool(item.get("break_board_flag")),
                            _bool(item.get("relimit_after_break_flag")), _num(item.get("turnover_rate")),
                            _num(item.get("volume_ratio")), _num(item.get("seal_amount")), _num(item.get("seal_strength_score")),
                            int(item.get("opened_times") or 0), _num(item.get("intraday_fade_score")),
                            _num(item.get("open_price")), _num(item.get("high_price")), _num(item.get("low_price")),
                            _num(item.get("close_price")), _text(item.get("calculated_at")), item.get("feature_hash"),
                        ),
                    )
                    inserted += 1 if conn.total_changes > before else 0
                elif feature_type == "hot_execution_feature_snapshot_v1":
                    before = conn.total_changes
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO hot_execution_feature_snapshot_v1 (feature_id, hot_case_id, symbol,
                            calc_stage, auction_price, auction_matched_amount, auction_imbalance_ratio, open_5m_vwap,
                            entry_vs_vwap_deviation_pct, open_gap_pct, open_overheat_score, no_fill_risk_score,
                            calculated_at, feature_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["feature_id"], item.get("hot_case_id"), item["symbol"], item["calc_stage"],
                            _num(item.get("auction_price")), _num(item.get("auction_matched_amount")),
                            _num(item.get("auction_imbalance_ratio")), _num(item.get("open_5m_vwap")),
                            _num(item.get("entry_vs_vwap_deviation_pct")), _num(item.get("open_gap_pct")),
                            _num(item.get("open_overheat_score")), _num(item.get("no_fill_risk_score")),
                            _text(item.get("calculated_at")), item.get("feature_hash"),
                        ),
                    )
                    inserted += 1 if conn.total_changes > before else 0
        return inserted

    def upsert_active_case_registry(self, record: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO hot_active_case_registry_v1 (hot_case_id, hot_cycle_id, tracking_pool, priority_level,
                    next_observe_at, last_observe_at, observe_frequency_seconds, case_status, close_reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hot_case_id) DO UPDATE SET
                    tracking_pool=excluded.tracking_pool,
                    priority_level=excluded.priority_level,
                    next_observe_at=excluded.next_observe_at,
                    last_observe_at=excluded.last_observe_at,
                    observe_frequency_seconds=excluded.observe_frequency_seconds,
                    case_status=excluded.case_status,
                    close_reason=excluded.close_reason,
                    updated_at=excluded.updated_at
                """,
                (
                    record["hot_case_id"], record["hot_cycle_id"], record["tracking_pool"], int(record.get("priority_level") or 0),
                    _text(record.get("next_observe_at")), _text(record.get("last_observe_at")),
                    int(record.get("observe_frequency_seconds") or 300), record.get("case_status") or "active",
                    record.get("close_reason"), _text(record.get("updated_at")),
                ),
            )

    def due_active_cases(self, *, now: datetime, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT r.*, c.symbol, c.stock_name, c.trade_date
            FROM hot_active_case_registry_v1 r
            JOIN hot_decision_case_v1 c ON c.hot_case_id = r.hot_case_id
            WHERE r.case_status = 'active' AND r.next_observe_at <= ?
            ORDER BY r.priority_level DESC, r.next_observe_at ASC
            LIMIT ?
            """,
            (now.isoformat(), int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]

    def append_observations_bulk(self, observations: list[dict[str, Any]]) -> int:
        """Append observations and update latest_state/active registry in one transaction.

        The append-only snapshot remains the training/audit truth. latest_state is only
        a fast current-state projection for scheduling and front-end reads.
        """
        inserted = 0
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            for obs in observations:
                before = conn.total_changes
                conn.execute(
                    """
                    INSERT OR IGNORE INTO hot_observation_snapshot_v1 (observation_id, hot_case_id, hot_cycle_id,
                        observe_seq, observe_time, data_as_of, observe_stage, latest_price, reference_entry_price,
                        return_from_reference_pct, mfe_pct, mae_pct, first_event_type, expectation_state,
                        deviation_reason_codes, support_strength_score, contradiction_score, freshness_status,
                        quality_status, sequence_no, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obs["observation_id"], obs["hot_case_id"], obs["hot_cycle_id"], int(obs.get("observe_seq") or 0),
                        _text(obs.get("observe_time")), _text(obs.get("data_as_of")), obs.get("observe_stage"),
                        _num(obs.get("latest_price")), _num(obs.get("reference_entry_price")), _num(obs.get("return_from_reference_pct")),
                        _num(obs.get("mfe_pct")), _num(obs.get("mae_pct")), obs.get("first_event_type"), obs.get("expectation_state"),
                        _json(obs.get("deviation_reason_codes") or []), _num(obs.get("support_strength_score")),
                        _num(obs.get("contradiction_score")), obs.get("freshness_status"), obs.get("quality_status"),
                        int(obs.get("sequence_no") or obs.get("observe_seq") or 0), now,
                    ),
                )
                if conn.total_changes > before:
                    inserted += 1
                    status = "monitoring"
                    if obs.get("first_event_type") == "target_hit":
                        status = "target_hit"
                    elif obs.get("first_event_type") == "invalidation_hit":
                        status = "invalidation_hit"
                    conn.execute(
                        """
                        INSERT INTO hot_case_latest_state_v1 (hot_case_id, hot_cycle_id, latest_observation_id,
                            latest_price, return_from_reference_pct, mfe_pct, mae_pct, first_event_type, expectation_state,
                            freshness_status, quality_status, monitoring_status, sequence_no, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(hot_case_id) DO UPDATE SET
                            hot_cycle_id=excluded.hot_cycle_id,
                            latest_observation_id=excluded.latest_observation_id,
                            latest_price=excluded.latest_price,
                            return_from_reference_pct=excluded.return_from_reference_pct,
                            mfe_pct=excluded.mfe_pct,
                            mae_pct=excluded.mae_pct,
                            first_event_type=excluded.first_event_type,
                            expectation_state=excluded.expectation_state,
                            freshness_status=excluded.freshness_status,
                            quality_status=excluded.quality_status,
                            monitoring_status=excluded.monitoring_status,
                            sequence_no=excluded.sequence_no,
                            updated_at=excluded.updated_at
                        WHERE excluded.sequence_no >= hot_case_latest_state_v1.sequence_no
                        """,
                        (
                            obs["hot_case_id"], obs["hot_cycle_id"], obs["observation_id"], _num(obs.get("latest_price")),
                            _num(obs.get("return_from_reference_pct")), _num(obs.get("mfe_pct")), _num(obs.get("mae_pct")),
                            obs.get("first_event_type"), obs.get("expectation_state"), obs.get("freshness_status"),
                            obs.get("quality_status"), status, int(obs.get("sequence_no") or obs.get("observe_seq") or 0), now,
                        ),
                    )
                    close_reason = None
                    case_status = "active"
                    if status in {"target_hit", "invalidation_hit"}:
                        case_status = "closed"
                        close_reason = status
                    freq = 1800 if case_status == "closed" else 300
                    conn.execute(
                        """
                        UPDATE hot_active_case_registry_v1
                        SET last_observe_at = ?, next_observe_at = ?, case_status = ?, close_reason = ?, updated_at = ?
                        WHERE hot_case_id = ?
                        """,
                        (
                            _text(obs.get("observe_time")),
                            (_parse_sqlite_time(_text(obs.get("observe_time"))) + timedelta(seconds=freq)).isoformat(),
                            case_status,
                            close_reason,
                            now,
                            obs["hot_case_id"],
                        ),
                    )
        return inserted

    def latest_state(self, hot_case_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM hot_case_latest_state_v1 WHERE hot_case_id = ?", (hot_case_id,)).fetchone()
        return dict(row) if row else None

    def apply_calibration_version(self, versioned: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        report = versioned.get("report") or {}
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO hot_calibration_job_v1 (calibration_job_id, calibration_version, training_window_start,
                    training_window_end, calibration_cutoff_time, raw_sample_count, mature_sample_count, can_activate,
                    activation_status, report_json, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"cal-job-{versioned['calibration_version']}", versioned["calibration_version"],
                    versioned["training_window_start"], versioned["training_window_end"],
                    _text(versioned["calibration_cutoff_time"]), int(versioned.get("raw_sample_count") or 0),
                    int(versioned.get("mature_sample_count") or 0), _bool(versioned.get("can_activate")),
                    versioned.get("activation_status"), _json(report), now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO hot_teacher_calibration_version_v1 (calibration_version, training_window_start,
                    training_window_end, calibration_cutoff_time, mature_sample_count, min_total_samples, activation_status,
                    is_active, activated_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    versioned["calibration_version"], versioned["training_window_start"], versioned["training_window_end"],
                    _text(versioned["calibration_cutoff_time"]), int(versioned.get("mature_sample_count") or 0),
                    int(versioned.get("min_total_samples") or (report.get("activation_gate") or {}).get("min_total_samples") or 120),
                    versioned.get("activation_status"), _bool(versioned.get("can_activate")),
                    _text(versioned["calibration_cutoff_time"]) if versioned.get("can_activate") else None,
                    now,
                ),
            )

    def build_model_version_evaluation(self, *, model_version: str = "hot_candidates_v2_lifecycle") -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT direction_outcome, execution_outcome, mfe_pct, mae_pct
            FROM hot_outcome_label_v1
            """
        ).fetchall()
        sample_count = len(rows)
        if sample_count == 0:
            success_rate = execution_rate = avg_mfe = avg_mae = None
        else:
            success_rate = sum(1 for row in rows if row["direction_outcome"] == "direction_success") / sample_count * 100
            execution_rate = sum(1 for row in rows if row["execution_outcome"] == "executable") / sample_count * 100
            mfe_values = [float(row["mfe_pct"]) for row in rows if row["mfe_pct"] is not None]
            mae_values = [float(row["mae_pct"]) for row in rows if row["mae_pct"] is not None]
            avg_mfe = sum(mfe_values) / len(mfe_values) if mfe_values else None
            avg_mae = sum(mae_values) / len(mae_values) if mae_values else None
        failure_rows = self.conn.execute(
            """
            SELECT failure_causality_type, primary_failure_reason, COUNT(*) AS n
            FROM hot_failure_attribution_v1
            WHERE failure_causality_type NOT IN ('not_failure', 'not_failed')
            GROUP BY failure_causality_type, primary_failure_reason
            ORDER BY n DESC
            """
        ).fetchall()
        evaluation = {
            "contract_kind": "hot_model_version_evaluation_v1",
            "model_version_evaluation_id": f"hot-eval-{model_version}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "model_version": model_version,
            "sample_count": sample_count,
            "official_signal_count": self.table_count("hot_signal_fact_v1"),
            "direction_success_rate": success_rate,
            "execution_success_rate": execution_rate,
            "avg_mfe_pct": avg_mfe,
            "avg_mae_pct": avg_mae,
            "systematic_failure_json": [dict(row) for row in failure_rows],
            "version_status": "candidate" if sample_count < 120 else "ready_for_shadow_review",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.conn.execute(
            """
            INSERT INTO hot_model_version_evaluation_v1 (model_version_evaluation_id, model_version, sample_count,
                official_signal_count, direction_success_rate, execution_success_rate, avg_mfe_pct, avg_mae_pct,
                systematic_failure_json, version_status, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation["model_version_evaluation_id"], model_version, sample_count, evaluation["official_signal_count"],
                evaluation["direction_success_rate"], evaluation["execution_success_rate"], evaluation["avg_mfe_pct"],
                evaluation["avg_mae_pct"], _json(evaluation["systematic_failure_json"]), evaluation["version_status"],
                evaluation["generated_at"],
            ),
        )
        self.conn.commit()
        return evaluation


    def apply_teacher_calibration_report(self, report: dict[str, Any]) -> int:
        """Persist generated bucket calibration rows into the local validation store."""
        rows = list(report.get("bucket_calibrations") or [])
        now = _text(report.get("generated_at")) or datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            for row in rows:
                calibration_row_id = f"cal-{row.get('calibration_version')}-{row.get('lifecycle_stage')}-{row.get('probability_bucket')}-{row.get('market_regime_bucket')}-{row.get('sector_heat_bucket')}"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO hot_teacher_calibration_v1 (calibration_row_id, calibration_version, lifecycle_stage,
                        probability_bucket, market_regime_bucket, sector_heat_bucket, sample_count, evaluated_count, hit_count,
                        realized_hit_rate, avg_predicted_probability, calibration_error, brier_score, lift_vs_overall, can_activate,
                        recommended_action, generated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        calibration_row_id, row.get("calibration_version"), row.get("lifecycle_stage"), row.get("probability_bucket"),
                        row.get("market_regime_bucket") or "all", row.get("sector_heat_bucket") or "all",
                        int(row.get("sample_count") or 0), int(row.get("evaluated_count") or 0), int(row.get("hit_count") or 0),
                        _num(row.get("realized_hit_rate")), _num(row.get("avg_predicted_probability")), _num(row.get("calibration_error")),
                        _num(row.get("brier_score")), _num(row.get("lift_vs_overall")), _bool(row.get("can_activate")),
                        row.get("recommended_action"), now,
                    ),
                )
        return len(rows)
