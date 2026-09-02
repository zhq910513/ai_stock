from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

HOT_POSTGRES_REPOSITORY_VERSION = "hot_postgres_repository_v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
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


def _bool(value: Any) -> bool:
    return bool(value)


@dataclass(frozen=True)
class SqlStatement:
    name: str
    sql: str
    params: tuple[Any, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "sql": self.sql, "params": list(self.params)}


@dataclass(frozen=True)
class HotPostgresWriteSummary:
    contract_kind: str
    repository_version: str
    statement_count: int
    hot_case_id: str
    hot_cycle_id: str
    hot_signal_id: str
    executed_statement_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HotPostgresWritePlanBuilder:
    """Builds production SQL for decision_hot.* without mixing other model domains."""

    def build(self, pipeline: dict[str, Any]) -> list[SqlStatement]:
        research = pipeline["research_contract"]
        cycle = research["hot_cycle"]
        case = research["hot_decision_case"]
        teacher = research.get("teacher_calibration") or {}
        initial = research["initial_decision_snapshot"]
        stage = research["stage_scores"]
        release = research["release_gate"]
        signal = pipeline["hot_signal"]
        buy = pipeline["buy_point"]
        outcome = pipeline["outcome_label"]
        failure = pipeline["failure_attribution"]
        distortion = pipeline["first_output_distortion_analysis"]
        evolution = pipeline["evolution_sample"]
        research_pool = pipeline.get("research_sample_pool") or {}
        now = datetime.now(timezone.utc)
        statements: list[SqlStatement] = [
            SqlStatement(
                "upsert_hot_cycle",
                """
                INSERT INTO decision_hot.hot_cycle_v1 (hot_cycle_id, symbol, stock_name, cycle_start_date,
                    cycle_start_reason, latest_lifecycle_stage, max_board_count, primary_theme, primary_catalyst_id,
                    cycle_status, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',now(),now())
                ON CONFLICT (hot_cycle_id) DO UPDATE SET
                    latest_lifecycle_stage=EXCLUDED.latest_lifecycle_stage,
                    max_board_count=GREATEST(decision_hot.hot_cycle_v1.max_board_count, EXCLUDED.max_board_count),
                    updated_at=now()
                """,
                (
                    cycle["hot_cycle_id"], cycle["symbol"], cycle.get("stock_name"), cycle.get("cycle_start_date"),
                    cycle.get("cycle_start_reason"), cycle.get("lifecycle_stage"), int(cycle.get("board_count") or 0),
                    cycle.get("primary_theme"), cycle.get("primary_catalyst_id"),
                ),
            ),
            SqlStatement(
                "upsert_hot_case",
                """
                INSERT INTO decision_hot.hot_decision_case_v1 (hot_case_id, hot_cycle_id, batch_id, candidate_id,
                    instrument_id, symbol, stock_name, trade_date, decision_time, lifecycle_stage_at_decision,
                    board_count_at_decision, p_limit_up_raw, p_limit_up_calibrated, case_status, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',now(),now())
                ON CONFLICT (hot_case_id) DO UPDATE SET updated_at=now()
                """,
                (
                    case["hot_case_id"], case["hot_cycle_id"], case.get("batch_id"), case.get("candidate_id"),
                    case.get("instrument_id"), case["symbol"], case.get("stock_name"), case.get("trade_date"),
                    _text(case.get("decision_time")), case.get("lifecycle_stage_at_decision"),
                    int(case.get("board_count_at_decision") or 0), _num(teacher.get("teacher_prior_raw")),
                    _num(teacher.get("teacher_prior_calibrated")),
                ),
            ),
            SqlStatement(
                "insert_initial_snapshot_once",
                """
                INSERT INTO decision_hot.hot_initial_decision_snapshot_v1 (initial_snapshot_id, hot_case_id, hot_cycle_id,
                    decision_time, model_version, first_score, first_lifecycle_stage, first_teacher_prior_raw,
                    first_teacher_prior_calibrated, first_release_gate_status, is_immutable_first_decision,
                    positive_factors_json, negative_factors_json, snapshot_json, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s::jsonb,%s::jsonb,%s::jsonb,now())
                ON CONFLICT (initial_snapshot_id) DO NOTHING
                """,
                (
                    initial["initial_snapshot_id"], initial["hot_case_id"], initial["hot_cycle_id"], _text(initial.get("decision_time")),
                    initial.get("model_version"), _num(initial.get("first_score")), initial.get("first_lifecycle_stage"),
                    _num(initial.get("first_teacher_prior_raw")), _num(initial.get("first_teacher_prior_calibrated")),
                    initial.get("first_release_gate_status"), _json(initial.get("positive_factors") or []),
                    _json(initial.get("negative_factors") or []), _json(initial),
                ),
            ),
            SqlStatement(
                "insert_score_fact",
                """
                INSERT INTO decision_hot.hot_score_fact_v1 (hot_case_id, model_version, score_stage, pre_auction_score,
                    auction_confirmed_score, open_5m_confirmed_score, official_hot_score, scoring_state,
                    recommendation_eligibility, main_positive_factors_json, main_negative_factors_json,
                    hard_block_reasons_json, warning_reasons_json, score_hash, created_at)
                VALUES (%s,%s,'official',%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,now())
                """,
                (
                    case["hot_case_id"], stage.get("score_model_version") or pipeline.get("model_version"),
                    _num(stage.get("pre_auction_score")), _num(stage.get("auction_confirmed_score")),
                    _num(stage.get("open_5m_confirmed_score")), _num(stage.get("official_hot_score")),
                    "scored" if stage.get("official_hot_score") is not None else "score_incomplete",
                    release.get("recommendation_eligibility"), _json(initial.get("positive_factors") or []),
                    _json(initial.get("negative_factors") or []), _json(release.get("block_reasons") or []),
                    _json(release.get("warning_reasons") or []), stage.get("score_hash") or "no-score-hash",
                ),
            ),
            SqlStatement(
                "insert_release_gate",
                """
                INSERT INTO decision_hot.hot_release_gate_audit_v1 (hot_case_id, gate_version, gate_time, gate_status,
                    official_signal_allowed, signal_stage, block_reasons_json, warning_reasons_json,
                    required_evidence_status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,now())
                """,
                (
                    case["hot_case_id"], release.get("gate_version"), _text(case.get("decision_time")), release.get("gate_status"),
                    _bool(release.get("official_signal_allowed")), release.get("signal_stage"),
                    _json(release.get("block_reasons") or []), _json(release.get("warning_reasons") or []),
                    release.get("required_evidence_status") or "unknown",
                ),
            ),
            SqlStatement(
                "upsert_hot_signal",
                """
                INSERT INTO decision_hot.hot_signal_fact_v1 (hot_signal_id, hot_case_id, hot_cycle_id, symbol, signal_date,
                    selected_at, decision_time, model_version, model_score, signal_stage, is_official_signal,
                    is_research_only, release_gate_status, release_gate_reason, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now(),now())
                ON CONFLICT (hot_signal_id) DO UPDATE SET updated_at=now()
                """,
                (
                    signal["hot_signal_id"], signal["hot_case_id"], signal["hot_cycle_id"], signal["symbol"], signal.get("signal_date"),
                    _text(signal.get("selected_at")), _text(signal.get("decision_time")), signal.get("model_version"),
                    _num(signal.get("model_score")), signal.get("signal_stage"), _bool(signal.get("is_official_signal")),
                    _bool(signal.get("is_research_only")), signal.get("release_gate_status"), _json(signal.get("release_gate_reason") or []),
                ),
            ),
        ]
        if buy.get("buy_point_id"):
            statements.append(
                SqlStatement(
                    "insert_frozen_buy_point_once",
                    """
                    INSERT INTO decision_hot.hot_buy_point_v1 (buy_point_id, hot_signal_id, hot_case_id, hot_cycle_id, adapter_code,
                        buy_point_version, calc_stage, reference_entry_price, entry_price_low, entry_price_high,
                        target_price, invalidation_price, risk_reward_ratio, buy_point_status, block_reason,
                        calculated_at, data_as_of, is_first_valid, is_frozen_reference, decision_trace_json, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())
                    ON CONFLICT (buy_point_id) DO NOTHING
                    """,
                    (
                        buy["buy_point_id"], buy.get("hot_signal_id") or signal["hot_signal_id"], buy["hot_case_id"], buy.get("hot_cycle_id") or signal.get("hot_cycle_id"),
                        buy.get("adapter_code"), buy.get("adapter_version"), buy.get("calc_stage"),
                        _num(buy.get("reference_entry_price")), _num(buy.get("entry_price_low")), _num(buy.get("entry_price_high")),
                        _num(buy.get("target_price")), _num(buy.get("invalidation_price")), _num(buy.get("risk_reward_ratio")),
                        buy.get("buy_point_status"), buy.get("block_reason"), _text(buy.get("calculated_at")),
                        _text(buy.get("data_as_of")), _bool(buy.get("is_first_valid")), _bool(buy.get("is_frozen_reference")),
                        _json(buy.get("decision_trace_json") or {}),
                    ),
                )
            )
        for obs in list(pipeline.get("observations") or []):
            statements.append(
                SqlStatement(
                    "insert_observation_append_only",
                    """
                    INSERT INTO decision_hot.hot_observation_snapshot_v1 (observation_id, hot_case_id, hot_cycle_id,
                        observe_seq, observe_time, data_as_of, observe_stage, latest_price, reference_entry_price,
                        return_from_reference_pct, mfe_pct, mae_pct, first_event_type, expectation_state,
                        deviation_reason_codes, support_strength_score, contradiction_score, freshness_status,
                        quality_status, sequence_no, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::text[],%s,%s,%s,%s,%s,now())
                    ON CONFLICT (hot_case_id, observe_seq) DO NOTHING
                    """,
                    (
                        obs["observation_id"], obs["hot_case_id"], obs["hot_cycle_id"], int(obs.get("observe_seq") or 0),
                        _text(obs.get("observe_time")), _text(obs.get("data_as_of")), obs.get("observe_stage"),
                        _num(obs.get("latest_price")), _num(obs.get("reference_entry_price")), _num(obs.get("return_from_reference_pct")),
                        _num(obs.get("mfe_pct")), _num(obs.get("mae_pct")), obs.get("first_event_type"), obs.get("expectation_state"),
                        list(obs.get("deviation_reason_codes") or []), _num(obs.get("support_strength_score")), _num(obs.get("contradiction_score")),
                        obs.get("freshness_status"), obs.get("quality_status"), int(obs.get("sequence_no") or obs.get("observe_seq") or 0),
                    ),
                )
            )
        statements.extend([
            SqlStatement(
                "upsert_outcome_label",
                """
                INSERT INTO decision_hot.hot_outcome_label_v1 (hot_case_id, hot_signal_id, label_version, direction_outcome,
                    execution_outcome, path_outcome, environment_outcome, data_outcome, validation_status, t5_status,
                    t20_status, first_target_hit_at, first_invalidation_hit_at, first_event_type, actual_days_to_target,
                    mfe_pct, mae_pct, max_return_pct, max_drawdown_pct, relative_market_return_pct,
                    relative_sector_return_pct, label_maturity_status, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (hot_case_id, label_version) DO UPDATE SET updated_at=now(),
                    direction_outcome=EXCLUDED.direction_outcome,
                    execution_outcome=EXCLUDED.execution_outcome,
                    validation_status=EXCLUDED.validation_status,
                    label_maturity_status=EXCLUDED.label_maturity_status
                """,
                (
                    outcome["hot_case_id"], signal["hot_signal_id"], outcome.get("label_version"), outcome.get("direction_outcome"),
                    outcome.get("execution_outcome"), outcome.get("path_outcome"), outcome.get("environment_outcome"),
                    outcome.get("data_outcome"), outcome.get("validation_status"), outcome.get("t5_status"), outcome.get("t20_status"),
                    _text(outcome.get("first_target_hit_at")), _text(outcome.get("first_invalidation_hit_at")), outcome.get("first_event_type"),
                    outcome.get("actual_days_to_target"), _num(outcome.get("mfe_pct")), _num(outcome.get("mae_pct")),
                    _num(outcome.get("max_return_pct")), _num(outcome.get("max_drawdown_pct")),
                    _num(outcome.get("relative_market_return_pct")), _num(outcome.get("relative_sector_return_pct")),
                    outcome.get("label_maturity_status"),
                ),
            ),
            SqlStatement(
                "insert_failure_attribution",
                """
                INSERT INTO decision_hot.hot_failure_attribution_v1 (hot_case_id, failure_causality_type,
                    primary_failure_reason, secondary_failure_reasons_json, similar_case_bucket, similar_case_count,
                    similar_case_failure_rate_pct, is_systematic_pattern, evidence_json, created_at)
                VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb,now())
                """,
                (
                    failure["hot_case_id"], failure.get("failure_causality_type"), failure.get("primary_failure_reason"),
                    _json(failure.get("secondary_failure_reasons") or []), failure.get("similar_case_bucket"),
                    failure.get("similar_case_count"), _num(failure.get("similar_case_failure_rate_pct")),
                    _bool(failure.get("is_systematic_pattern")), _json(failure.get("evidence_json") or {}),
                ),
            ),
            SqlStatement(
                "insert_distortion_analysis",
                """
                INSERT INTO decision_hot.hot_first_output_distortion_analysis_v1 (hot_case_id, first_model_version,
                    first_score, first_lifecycle_stage, first_teacher_prior_raw, first_teacher_prior_calibrated,
                    final_outcome, distortion_type, primary_distortion_factor, secondary_distortion_factors,
                    is_systematic_pattern, recommended_correction, analysis_status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,now())
                """,
                (
                    distortion["hot_case_id"], distortion.get("first_model_version"), _num(distortion.get("first_score")),
                    distortion.get("first_lifecycle_stage"), _num(distortion.get("first_teacher_prior_raw")),
                    _num(distortion.get("first_teacher_prior_calibrated")), distortion.get("final_outcome"),
                    distortion.get("distortion_type"), distortion.get("primary_distortion_factor"),
                    _json(distortion.get("secondary_distortion_factors") or []), _bool(distortion.get("is_systematic_pattern")),
                    _json(distortion.get("recommended_correction") or {}), distortion.get("analysis_status"),
                ),
            ),
            *(
                [SqlStatement(
                    "insert_evolution_sample",
                    """
                    INSERT INTO decision_hot.hot_evolution_sample_v1 (evolution_sample_id, hot_case_id, hot_cycle_id,
                        source_observation_id, sample_type, lifecycle_stage_at_decision, feature_at_decision_json,
                        observation_summary_json, outcome_label, execution_label, failure_reason, correction_direction,
                        recommended_adjustment_json, sample_weight, maturity_status, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s,%s,now())
                    ON CONFLICT (evolution_sample_id) DO NOTHING
                    """,
                    (
                        evolution["evolution_sample_id"], evolution.get("hot_case_id"), evolution.get("hot_cycle_id"),
                        evolution.get("source_observation_id"), evolution.get("sample_type"), evolution.get("lifecycle_stage_at_decision"),
                        _json(evolution.get("feature_at_decision_json") or {}), _json(evolution.get("observation_summary_json") or {}),
                        evolution.get("outcome_label"), evolution.get("execution_label"), evolution.get("failure_reason"),
                        evolution.get("correction_direction"), _json(evolution.get("recommended_adjustment_json") or {}),
                        _num(evolution.get("sample_weight")) or 1.0, evolution.get("maturity_status"),
                    ),
                )]
                if evolution.get("evolution_sample_id") else []
            ),
        ])
        if research_pool.get("pool_record_id"):
            statements.append(
                SqlStatement(
                    "upsert_research_sample_pool",
                    """
                    INSERT INTO decision_hot.hot_research_sample_pool_v1 (pool_record_id, hot_case_id, hot_cycle_id, symbol,
                        trade_date, lifecycle_stage, probability_bucket, teacher_prior_raw, official_hot_score,
                        release_gate_status, signal_stage, tracking_pool, should_track, tracking_frequency_hint,
                        tracking_reason_codes, include_in_official_success_rate, include_in_teacher_calibration,
                        include_in_model_evolution, generated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
                    ON CONFLICT (pool_record_id) DO UPDATE SET
                        tracking_pool=EXCLUDED.tracking_pool,
                        should_track=EXCLUDED.should_track,
                        tracking_reason_codes=EXCLUDED.tracking_reason_codes,
                        generated_at=EXCLUDED.generated_at
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
            )
        return statements


class HotPostgresRepository:
    """Production Postgres writer for the hot model.

    Accepts an injected psycopg connection for tests or deployment. The class avoids a
    hard import of psycopg so unit tests can validate SQL contracts without the driver.
    """

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.builder = HotPostgresWritePlanBuilder()

    @classmethod
    def connect(cls, dsn: str) -> "HotPostgresRepository":
        try:
            import psycopg  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("psycopg is required for Postgres persistence but is not installed") from exc
        return cls(psycopg.connect(dsn))

    def apply_pipeline(self, pipeline: dict[str, Any]) -> HotPostgresWriteSummary:
        statements = self.builder.build(pipeline)
        names: list[str] = []
        with self.connection.cursor() as cur:
            for statement in statements:
                cur.execute(statement.sql, statement.params)
                names.append(statement.name)
        self.connection.commit()
        research = pipeline["research_contract"]
        return HotPostgresWriteSummary(
            contract_kind="hot_postgres_write_summary_v1",
            repository_version=HOT_POSTGRES_REPOSITORY_VERSION,
            statement_count=len(statements),
            hot_case_id=research["hot_decision_case"]["hot_case_id"],
            hot_cycle_id=research["hot_cycle"]["hot_cycle_id"],
            hot_signal_id=pipeline["hot_signal"]["hot_signal_id"],
            executed_statement_names=names,
        )
