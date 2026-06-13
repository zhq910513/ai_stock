from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


class MemoryPostgresRepository:
    """PostgreSQL repository contract for candidate_memory production stages.

    The class intentionally accepts a generic DB-API/psycopg-like connection so tests can validate SQL and
    transaction boundaries without requiring a local PostgreSQL server. It mirrors the model rules:
    append-only snapshots, upsert-only projections, due registry selection, and explicit stage writes.
    """

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: MemoryPostgresRepository._jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [MemoryPostgresRepository._jsonable(item) for item in value]
        return value

    @classmethod
    def _json(cls, value: Any) -> str:
        return json.dumps(cls._jsonable(value), ensure_ascii=False, sort_keys=True)

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        cur = self.connection.cursor()
        cur.execute(sql, params)
        return cur

    def _commit(self) -> None:
        commit = getattr(self.connection, "commit", None)
        if callable(commit):
            commit()

    def _rollback(self) -> None:
        rollback = getattr(self.connection, "rollback", None)
        if callable(rollback):
            rollback()

    def get_due_active_cases(self, *, as_of_time_utc: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        sql = """
            SELECT memory_entity_id, symbol, tracking_pool, priority_level, next_observe_at,
                   last_observe_at, observe_frequency_seconds, memory_status, budget_class, close_reason
            FROM decision_memory.memory_active_case_registry_v1
            WHERE memory_status NOT IN ('closed','invalidated','expired_closed','structure_invalidated')
              AND next_observe_at <= %s
            ORDER BY priority_level DESC, next_observe_at ASC
            LIMIT %s
        """
        cur = self._execute(sql, (as_of_time_utc, int(limit)))
        rows = getattr(cur, "fetchall", lambda: [])()
        out: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                out.append(row)
            else:
                columns = [desc[0] for desc in getattr(cur, "description", [])]
                out.append(dict(zip(columns, row, strict=False)))
        return out

    def upsert_registry(self, registry: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_active_case_registry_v1 (
              memory_entity_id, symbol, tracking_pool, priority_level, next_observe_at, last_observe_at,
              observe_frequency_seconds, memory_status, budget_class, close_reason, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(memory_entity_id) DO UPDATE SET
              symbol=EXCLUDED.symbol,
              tracking_pool=EXCLUDED.tracking_pool,
              priority_level=EXCLUDED.priority_level,
              next_observe_at=EXCLUDED.next_observe_at,
              last_observe_at=EXCLUDED.last_observe_at,
              observe_frequency_seconds=EXCLUDED.observe_frequency_seconds,
              memory_status=EXCLUDED.memory_status,
              budget_class=EXCLUDED.budget_class,
              close_reason=EXCLUDED.close_reason,
              updated_at=EXCLUDED.updated_at
        """
        self._execute(
            sql,
            (
                registry["memory_entity_id"],
                registry["symbol"],
                registry.get("tracking_pool") or "memory_observation_pool",
                int(registry.get("priority_level") or 0),
                registry["next_observe_at"],
                registry.get("last_observe_at"),
                int(registry.get("observe_frequency_seconds") or 1800),
                registry.get("memory_status") or "observing",
                registry.get("budget_class") or "normal",
                registry.get("close_reason"),
                registry.get("updated_at") or datetime.now(timezone.utc),
            ),
        )
        self._commit()

    def append_observation(self, observation: dict[str, Any]) -> bool:
        sql = """
            INSERT INTO decision_memory.memory_observation_snapshot_v1 (
              observation_id, memory_entity_id, symbol, observe_seq, observe_time, data_as_of,
              latest_price, return_since_first_selected_pct, distance_to_first_high_pct,
              memory_value_score, pre_signal_score, fake_activation_risk_score, expectation_state,
              deviation_reason_codes_json, feature_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            ON CONFLICT(observation_id) DO NOTHING
        """
        cur = self._execute(
            sql,
            (
                observation["observation_id"],
                observation["memory_entity_id"],
                observation["symbol"],
                int(observation.get("observe_seq") or 0),
                observation["observe_time"],
                observation.get("data_as_of") or observation["observe_time"],
                observation.get("latest_price"),
                observation.get("return_since_first_selected_pct"),
                observation.get("distance_to_first_high_pct"),
                observation.get("memory_value_score"),
                observation.get("pre_signal_score"),
                observation.get("fake_activation_risk_score"),
                observation.get("expectation_state"),
                self._json(observation.get("deviation_reason_codes") or []),
                observation.get("feature_hash") or observation.get("observation_hash"),
            ),
        )
        self._commit()
        return getattr(cur, "rowcount", 0) == 1

    def upsert_latest_state(self, latest_state: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_latest_state_v1 (
              memory_entity_id, symbol, latest_observe_time, memory_status, memory_value_score,
              pre_signal_score, activation_quality_score, fake_activation_risk_score,
              latest_state_payload_json, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            ON CONFLICT(memory_entity_id) DO UPDATE SET
              symbol=EXCLUDED.symbol,
              latest_observe_time=EXCLUDED.latest_observe_time,
              memory_status=EXCLUDED.memory_status,
              memory_value_score=EXCLUDED.memory_value_score,
              pre_signal_score=EXCLUDED.pre_signal_score,
              activation_quality_score=EXCLUDED.activation_quality_score,
              fake_activation_risk_score=EXCLUDED.fake_activation_risk_score,
              latest_state_payload_json=EXCLUDED.latest_state_payload_json,
              updated_at=EXCLUDED.updated_at
        """
        self._execute(
            sql,
            (
                latest_state["memory_entity_id"],
                latest_state["symbol"],
                latest_state.get("latest_observe_time"),
                latest_state.get("memory_status") or "observing",
                latest_state.get("memory_value_score"),
                latest_state.get("pre_signal_score"),
                latest_state.get("activation_quality_score"),
                latest_state.get("fake_activation_risk_score"),
                self._json(latest_state.get("latest_state_payload") or latest_state),
                latest_state.get("updated_at") or datetime.now(timezone.utc),
            ),
        )
        self._commit()

    def save_pre_signal_case(self, pre_signal_case: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_pre_signal_case_v1 (
              pre_signal_case_id, memory_entity_id, symbol, detected_at, pre_signal_window_start,
              pre_signal_window_end, pre_signal_strength_score, pre_signal_types_json,
              fake_pre_signal_risk_score, ex_ante_event_count, post_hoc_event_count, status,
              feature_hash, hard_block_reasons_json, source_gap_codes_json, case_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
            ON CONFLICT(pre_signal_case_id) DO NOTHING
        """
        self._execute(
            sql,
            (
                pre_signal_case["pre_signal_case_id"],
                pre_signal_case["memory_entity_id"],
                pre_signal_case["symbol"],
                pre_signal_case.get("detected_at"),
                pre_signal_case.get("pre_signal_window_start"),
                pre_signal_case.get("pre_signal_window_end"),
                pre_signal_case.get("pre_signal_strength_score") or pre_signal_case.get("pre_signal_score"),
                self._json(pre_signal_case.get("pre_signal_types") or []),
                pre_signal_case.get("fake_pre_signal_risk_score") or pre_signal_case.get("fake_activation_risk_score"),
                int(pre_signal_case.get("ex_ante_event_count") or 0),
                int(pre_signal_case.get("post_hoc_event_count") or 0),
                pre_signal_case.get("status") or pre_signal_case.get("pre_signal_status") or "pre_signal_detected",
                pre_signal_case.get("feature_hash"),
                self._json(pre_signal_case.get("hard_block_reasons") or []),
                self._json(pre_signal_case.get("source_gap_codes") or []),
                pre_signal_case.get("case_hash") or pre_signal_case.get("pre_signal_hash"),
            ),
        )
        self._commit()

    def save_pre_limitup_signal_analysis(self, analysis: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_pre_limitup_signal_analysis_v1 (
              analysis_id, memory_entity_id, memory_signal_id, symbol, next_limit_up_date,
              lookback_window_days, earliest_detected_pre_signal_at, lead_days_before_limit_up,
              pre_signal_types_json, pre_signal_strength_score, false_positive_rate_bucket,
              matched_failed_case_count, matched_success_case_count, primary_up_reason,
              secondary_up_reasons_json, analysis_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s::jsonb,%s)
            ON CONFLICT(analysis_id) DO UPDATE SET
              lead_days_before_limit_up=EXCLUDED.lead_days_before_limit_up,
              pre_signal_types_json=EXCLUDED.pre_signal_types_json,
              pre_signal_strength_score=EXCLUDED.pre_signal_strength_score,
              false_positive_rate_bucket=EXCLUDED.false_positive_rate_bucket,
              matched_failed_case_count=EXCLUDED.matched_failed_case_count,
              matched_success_case_count=EXCLUDED.matched_success_case_count,
              primary_up_reason=EXCLUDED.primary_up_reason,
              analysis_hash=EXCLUDED.analysis_hash
        """
        self._execute(
            sql,
            (
                analysis["analysis_id"],
                analysis["memory_entity_id"],
                analysis.get("memory_signal_id"),
                analysis["symbol"],
                analysis.get("next_limit_up_date"),
                int(analysis.get("lookback_window_days") or 0),
                analysis.get("earliest_detected_pre_signal_at"),
                analysis.get("lead_days_before_limit_up"),
                self._json(analysis.get("pre_signal_types") or []),
                analysis.get("pre_signal_strength_score"),
                analysis.get("false_positive_rate_bucket"),
                int(analysis.get("matched_failed_case_count") or 0),
                int(analysis.get("matched_success_case_count") or 0),
                analysis.get("primary_up_reason"),
                self._json(analysis.get("secondary_up_reasons") or []),
                analysis.get("analysis_hash"),
            ),
        )
        self._commit()

    def apply_bulk_observation_result(self, result: dict[str, Any]) -> dict[str, int]:
        inserted = 0
        ignored = 0
        try:
            for observation in result.get("observations") or []:
                if self.append_observation(observation):
                    inserted += 1
                else:
                    ignored += 1
            for latest_state in result.get("latest_states") or []:
                self.upsert_latest_state(latest_state)
            for registry in result.get("registry_updates") or []:
                self.upsert_registry(registry)
        except Exception:
            self._rollback()
            raise
        return {
            "observations_inserted": inserted,
            "observations_ignored_duplicate": ignored,
            "latest_state_upserted": len(result.get("latest_states") or []),
            "registry_upserted": len(result.get("registry_updates") or []),
        }

    def save_memory_seed(self, seed: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_seed_v1 (
              seed_id, source_model, source_signal_id, source_case_id, symbol, selected_date,
              seed_status, seed_reasons_json, seed_score, source_payload_json, created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s)
            ON CONFLICT(seed_id) DO NOTHING
        """
        self._execute(
            sql,
            (
                seed["seed_id"],
                seed.get("source_model") or "hot_candidates",
                seed.get("source_signal_id") or seed.get("first_source_signal_id"),
                seed.get("source_case_id") or seed.get("first_source_case_id"),
                seed["symbol"],
                seed.get("selected_date") or seed.get("first_selected_date"),
                seed.get("seed_status") or "accepted",
                self._json(seed.get("seed_reasons") or []),
                seed.get("seed_score"),
                self._json(seed),
                seed.get("created_at") or datetime.now(timezone.utc),
            ),
        )
        self._commit()

    def upsert_memory_entity(self, entity: dict[str, Any], initial_snapshot: dict[str, Any] | None = None) -> None:
        sql_entity = """
            INSERT INTO decision_memory.memory_entity_v1 (
              memory_entity_id, symbol, first_source_model, first_source_signal_id,
              first_source_case_id, first_selected_date, memory_start_date, memory_status,
              ttl_days, ttl_expire_date, decay_score, memory_value_score, entity_payload_json, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            ON CONFLICT(memory_entity_id) DO UPDATE SET
              memory_status=EXCLUDED.memory_status,
              ttl_days=EXCLUDED.ttl_days,
              ttl_expire_date=EXCLUDED.ttl_expire_date,
              decay_score=EXCLUDED.decay_score,
              memory_value_score=EXCLUDED.memory_value_score,
              entity_payload_json=EXCLUDED.entity_payload_json,
              updated_at=EXCLUDED.updated_at
        """
        self._execute(
            sql_entity,
            (
                entity["memory_entity_id"],
                entity["symbol"],
                entity.get("first_source_model") or "hot_candidates",
                entity.get("first_source_signal_id"),
                entity.get("first_source_case_id"),
                entity.get("first_selected_date"),
                entity.get("memory_start_date"),
                entity.get("memory_status") or "observing",
                int(entity.get("ttl_days") or 30),
                entity.get("ttl_expire_date"),
                entity.get("decay_score"),
                entity.get("memory_value_score"),
                self._json(entity),
                entity.get("updated_at") or datetime.now(timezone.utc),
            ),
        )
        if initial_snapshot:
            sql_snapshot = """
                INSERT INTO decision_memory.memory_initial_snapshot_v1 (
                  memory_entity_id, symbol, snapshot_time, first_source_payload_json, snapshot_hash
                ) VALUES (%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT(memory_entity_id) DO NOTHING
            """
            self._execute(
                sql_snapshot,
                (
                    entity["memory_entity_id"],
                    entity["symbol"],
                    initial_snapshot.get("snapshot_time") or datetime.now(timezone.utc),
                    self._json(initial_snapshot),
                    initial_snapshot.get("snapshot_hash"),
                ),
            )
        self._commit()

    def save_activation_case(self, activation: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_activation_case_v1 (
              activation_case_id, memory_entity_id, symbol, activation_detected_at,
              activation_quality_score, trigger_reason_codes_json, fake_activation_risk_score,
              activation_status, case_payload_json, case_hash
            ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s)
            ON CONFLICT(activation_case_id) DO NOTHING
        """
        self._execute(
            sql,
            (
                activation["activation_case_id"],
                activation["memory_entity_id"],
                activation["symbol"],
                activation.get("activation_detected_at") or activation.get("detected_at"),
                activation.get("activation_quality_score"),
                self._json(activation.get("trigger_reason_codes") or activation.get("pre_signal_types") or []),
                activation.get("fake_activation_risk_score"),
                activation.get("activation_status") or "activation_ready",
                self._json(activation),
                activation.get("case_hash") or activation.get("activation_hash"),
            ),
        )
        self._commit()

    def save_release_gate_and_signal(self, release_gate: dict[str, Any]) -> None:
        sql_gate = """
            INSERT INTO decision_memory.memory_release_gate_audit_v1 (
              release_audit_id, memory_entity_id, activation_case_id, symbol, evaluated_at,
              release_gate_state, hard_block_reasons_json, recommendation_eligibility, audit_payload_json, audit_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s)
            ON CONFLICT(release_audit_id) DO NOTHING
        """
        audit_id = release_gate.get("release_audit_id") or f"rel-{release_gate.get('memory_entity_id')}-{release_gate.get('activation_case_id')}"
        self._execute(
            sql_gate,
            (
                audit_id,
                release_gate["memory_entity_id"],
                release_gate.get("activation_case_id"),
                release_gate["symbol"],
                release_gate.get("evaluated_at") or datetime.now(timezone.utc),
                release_gate.get("release_gate_state"),
                self._json(release_gate.get("hard_block_reasons") or []),
                release_gate.get("recommendation_eligibility"),
                self._json(release_gate),
                release_gate.get("audit_hash") or release_gate.get("release_hash"),
            ),
        )
        if release_gate.get("release_gate_state") == "official_signal_passed" and release_gate.get("memory_signal_id"):
            sql_signal = """
                INSERT INTO decision_memory.memory_signal_fact_v1 (
                  memory_signal_id, memory_entity_id, activation_case_id, symbol, signal_time,
                  signal_state, activation_quality_score, signal_payload_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(memory_signal_id) DO NOTHING
            """
            self._execute(
                sql_signal,
                (
                    release_gate["memory_signal_id"],
                    release_gate["memory_entity_id"],
                    release_gate.get("activation_case_id"),
                    release_gate["symbol"],
                    release_gate.get("evaluated_at") or datetime.now(timezone.utc),
                    "official_signal",
                    release_gate.get("activation_quality_score"),
                    self._json(release_gate),
                ),
            )
        self._commit()

    def save_buy_point(self, buy_point: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_buy_point_v1 (
              buy_point_id, memory_signal_id, memory_entity_id, activation_case_id, symbol,
              evaluated_at, buy_point_state, entry_stage, reference_entry_price,
              block_reasons_json, buy_point_payload_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
            ON CONFLICT(buy_point_id) DO NOTHING
        """
        self._execute(
            sql,
            (
                buy_point["buy_point_id"],
                buy_point.get("memory_signal_id"),
                buy_point["memory_entity_id"],
                buy_point.get("activation_case_id"),
                buy_point["symbol"],
                buy_point.get("evaluated_at") or datetime.now(timezone.utc),
                buy_point.get("buy_point_state"),
                buy_point.get("entry_stage"),
                buy_point.get("reference_entry_price"),
                self._json(buy_point.get("block_reasons") or []),
                self._json(buy_point),
            ),
        )
        self._commit()

    def save_mature_outcome(self, outcome: dict[str, Any]) -> None:
        if outcome.get("label_maturity_status") not in {"mature", "final"}:
            raise ValueError("pending outcome cannot be persisted as mature truth")
        sql = """
            INSERT INTO decision_memory.memory_outcome_label_v1 (
              outcome_id, memory_signal_id, memory_entity_id, activation_case_id, symbol,
              label_maturity_status, outcome_label, next_limit_up_hit, pre_signal_lead_days,
              include_official_success_rate, outcome_payload_json, matured_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            ON CONFLICT(outcome_id) DO UPDATE SET
              label_maturity_status=EXCLUDED.label_maturity_status,
              outcome_label=EXCLUDED.outcome_label,
              next_limit_up_hit=EXCLUDED.next_limit_up_hit,
              pre_signal_lead_days=EXCLUDED.pre_signal_lead_days,
              include_official_success_rate=EXCLUDED.include_official_success_rate,
              outcome_payload_json=EXCLUDED.outcome_payload_json,
              matured_at=EXCLUDED.matured_at
        """
        self._execute(
            sql,
            (
                outcome["outcome_id"],
                outcome.get("memory_signal_id"),
                outcome["memory_entity_id"],
                outcome.get("activation_case_id"),
                outcome["symbol"],
                outcome.get("label_maturity_status"),
                outcome.get("outcome_label"),
                bool(outcome.get("next_limit_up_hit")),
                outcome.get("pre_signal_lead_days"),
                bool(outcome.get("include_official_success_rate")),
                self._json(outcome),
                outcome.get("matured_at") or datetime.now(timezone.utc),
            ),
        )
        self._commit()

    def save_up_reason_attribution(self, attribution: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_up_reason_attribution_v1 (
              attribution_id, memory_signal_id, memory_entity_id, symbol, attributed_at,
              primary_up_reason, pre_signal_reason_codes_json, confirmed_up_reason_codes_json,
              post_hoc_explanation_codes_json, reason_confidence_score, attribution_payload_json, attribution_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s)
            ON CONFLICT(attribution_id) DO NOTHING
        """
        attribution_id = attribution.get("attribution_id") or f"upreason-{attribution.get('memory_signal_id') or attribution.get('memory_entity_id')}"
        self._execute(
            sql,
            (
                attribution_id,
                attribution.get("memory_signal_id"),
                attribution.get("memory_entity_id"),
                attribution.get("symbol"),
                attribution.get("attributed_at") or datetime.now(timezone.utc),
                attribution.get("primary_up_reason"),
                self._json(attribution.get("pre_signal_reason_codes") or []),
                self._json(attribution.get("confirmed_up_reason_codes") or []),
                self._json(attribution.get("post_hoc_explanation_codes") or []),
                attribution.get("reason_confidence_score"),
                self._json(attribution),
                attribution.get("attribution_hash"),
            ),
        )
        self._commit()

    def save_failure_attribution(self, attribution: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_failure_attribution_v1 (
              failure_attribution_id, memory_signal_id, memory_entity_id, symbol, attributed_at,
              failure_type, failure_reason_codes_json, model_failure_class, outcome_label,
              attribution_payload_json, attribution_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s)
            ON CONFLICT(failure_attribution_id) DO NOTHING
        """
        failure_attribution_id = attribution.get("failure_attribution_id") or f"fail-{attribution.get('memory_signal_id') or attribution.get('memory_entity_id')}"
        self._execute(
            sql,
            (
                failure_attribution_id,
                attribution.get("memory_signal_id"),
                attribution.get("memory_entity_id"),
                attribution.get("symbol"),
                attribution.get("attributed_at") or datetime.now(timezone.utc),
                attribution.get("failure_type"),
                self._json(attribution.get("failure_reason_codes") or []),
                attribution.get("model_failure_class"),
                attribution.get("outcome_label"),
                self._json(attribution),
                attribution.get("attribution_hash"),
            ),
        )
        self._commit()

    def save_evolution_sample(self, sample: dict[str, Any]) -> None:
        if sample.get("evolution_state") != "ready_for_offline_evolution":
            raise ValueError("only mature, eligible evolution samples can be persisted")
        sql = """
            INSERT INTO decision_memory.memory_evolution_sample_v1 (
              evolution_sample_id, memory_signal_id, memory_entity_id, symbol, created_at,
              evolution_state, evolution_labels_json, outcome_hash, sample_payload_json, evolution_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s)
            ON CONFLICT(evolution_sample_id) DO NOTHING
        """
        evolution_sample_id = sample.get("evolution_sample_id") or f"evo-{sample.get('memory_signal_id') or sample.get('memory_entity_id')}"
        self._execute(
            sql,
            (
                evolution_sample_id,
                sample.get("memory_signal_id"),
                sample.get("memory_entity_id"),
                sample.get("symbol"),
                sample.get("created_at") or datetime.now(timezone.utc),
                sample.get("evolution_state"),
                self._json(sample.get("evolution_labels") or []),
                sample.get("outcome_hash"),
                self._json(sample),
                sample.get("evolution_hash"),
            ),
        )
        self._commit()

    def save_model_version_shadow_evaluation(self, evaluation: dict[str, Any]) -> None:
        sql = """
            INSERT INTO decision_memory.memory_model_version_shadow_evaluation_v1 (
              evaluation_id, baseline_model_version, candidate_model_version, evaluated_at,
              evaluation_cutoff_time, eligible_sample_count, candidate_hit_rate_pct,
              baseline_hit_rate_pct, evaluation_state, hard_block_reasons_json, evaluation_payload_json, evaluation_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
            ON CONFLICT(evaluation_id) DO NOTHING
        """
        evaluation_id = evaluation.get("evaluation_id") or f"shadow-{evaluation.get('candidate_model_version')}-{evaluation.get('evaluation_cutoff_time')}"
        self._execute(
            sql,
            (
                evaluation_id,
                evaluation.get("baseline_model_version"),
                evaluation.get("candidate_model_version"),
                evaluation.get("evaluated_at") or datetime.now(timezone.utc),
                evaluation.get("evaluation_cutoff_time"),
                int(evaluation.get("eligible_sample_count") or 0),
                evaluation.get("candidate_hit_rate_pct"),
                evaluation.get("baseline_hit_rate_pct"),
                evaluation.get("evaluation_state"),
                self._json(evaluation.get("hard_block_reasons") or []),
                self._json(evaluation),
                evaluation.get("evaluation_hash"),
            ),
        )
        self._commit()
