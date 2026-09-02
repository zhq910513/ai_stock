from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from research_service.repository import ResearchPayloadRepository, jsonable, new_id, stable_hash
from research_service.schemas import ModelPayloadAssembleResponse
from research_service.task_registry import TaskRequirement


class ResearchDecisionMaterializer:
    def __init__(self, repository: ResearchPayloadRepository) -> None:
        self.repository = repository

    def materialize(
        self,
        *,
        task: TaskRequirement,
        assembly: ModelPayloadAssembleResponse,
        owner_response: dict[str, Any],
    ) -> dict[str, Any]:
        structured = owner_response.get("structured_output") if isinstance(owner_response.get("structured_output"), dict) else {}
        counts: dict[str, int] = defaultdict(int)
        gaps: list[str] = []
        if task.owner_service == "hot-candidates-service":
            self._materialize_hot(task, assembly, structured, counts)
        elif task.owner_service == "candidate-memory-service":
            gaps.extend(self._materialize_memory(task, assembly, structured, counts))
        elif task.owner_service == "ambush-watchlist-service":
            self._materialize_ambush(task, assembly, structured, counts)
        elif task.owner_service == "t-board-relay-service":
            counts["owner_repository_write_delegated"] += 1
        else:
            gaps.append(f"research_materializer_unknown_owner:{task.owner_service}")
        result = dict(counts)
        if gaps:
            result["materializer_gap_codes"] = gaps
        return result

    def _materialize_hot(
        self,
        task: TaskRequirement,
        assembly: ModelPayloadAssembleResponse,
        structured: dict[str, Any],
        counts: dict[str, int],
    ) -> None:
        output = structured.get("score_compute") or structured.get("release_gate_result") or structured.get("buy_point_result") or {}
        if not isinstance(output, dict):
            return
        symbol = _symbol(assembly)
        trade_date = assembly.trade_date
        as_of_time = assembly.as_of_time_utc or assembly.checked_at
        hot_signal = output.get("hot_signal") if isinstance(output.get("hot_signal"), dict) else {}
        buy_point = output.get("buy_point") if isinstance(output.get("buy_point"), dict) else {}
        upstream_case = _hot_upstream_case(assembly)
        is_score_compute = "score_compute" in structured
        if is_score_compute:
            hot_case_id = _first_non_empty(
                output.get("hot_case_id"),
                hot_signal.get("hot_case_id"),
                buy_point.get("hot_case_id"),
                upstream_case.get("hot_case_id"),
            )
        else:
            hot_case_id = _first_non_empty(
                upstream_case.get("hot_case_id"),
                output.get("hot_case_id"),
                hot_signal.get("hot_case_id"),
                buy_point.get("hot_case_id"),
            )
        if not hot_case_id and is_score_compute:
            hot_case_id = _id("hot-case", symbol, trade_date, assembly.payload_hash)
        if not hot_case_id:
            return
        owner_case_mismatch = _hot_case_id_mismatch(hot_case_id, output, hot_signal, buy_point)
        if is_score_compute:
            hot_cycle_id = _first_non_empty(
                output.get("hot_cycle_id"),
                hot_signal.get("hot_cycle_id"),
                buy_point.get("hot_cycle_id"),
                upstream_case.get("hot_cycle_id"),
                _id("hot-cycle", symbol),
            )
        else:
            hot_cycle_id = _first_non_empty(
                upstream_case.get("hot_cycle_id"),
                output.get("hot_cycle_id"),
                hot_signal.get("hot_cycle_id"),
                buy_point.get("hot_cycle_id"),
                _id("hot-cycle", symbol),
            )
        if "score_compute" in structured:
            stock_name = assembly.payload.get("name")
            batch_id = _int(assembly.payload.get("batch_id"))
            candidate_id = _int(assembly.payload.get("candidate_id"))
            instrument_id = _int(assembly.payload.get("instrument_id"))
            self._insert(
                "decision_hot.hot_cycle_v1",
                {
                    "hot_cycle_id": hot_cycle_id,
                    "symbol": symbol,
                    "stock_name": stock_name,
                    "cycle_start_date": trade_date,
                    "cycle_start_reason": "research_service_execution",
                    "latest_lifecycle_stage": task.model_phase or "research_execution",
                    "max_board_count": 0,
                    "cycle_status": "active",
                },
                counts,
            )
            self._insert(
                "decision_hot.hot_decision_case_v1",
                {
                    "hot_case_id": hot_case_id,
                    "hot_cycle_id": hot_cycle_id,
                    "batch_id": batch_id,
                    "candidate_id": candidate_id,
                    "instrument_id": instrument_id,
                    "symbol": symbol,
                    "stock_name": stock_name,
                    "trade_date": trade_date,
                    "decision_time": as_of_time,
                    "lifecycle_stage_at_decision": task.model_phase or "research_execution",
                    "board_count_at_decision": _int(assembly.payload.get("board_count")) or 0,
                    "p_limit_up_raw": assembly.payload.get("p_limit_up_raw") or assembly.payload.get("p_limit_up"),
                    "p_limit_up_calibrated": assembly.payload.get("p_limit_up_calibrated") or assembly.payload.get("p_limit_up"),
                    "case_status": "open",
                },
                counts,
            )
            self._materialize_hot_evidence(hot_case_id, assembly, counts)
            stage_scores = output.get("stage_scores") if isinstance(output.get("stage_scores"), dict) else {}
            self._insert(
                "decision_hot.hot_score_fact_v1",
                {
                    "hot_case_id": hot_case_id,
                    "model_version": owner_response_model_version(structured, default="hot_candidates_research_execution_v1"),
                    "score_stage": task.model_phase or "auction_confirmed_score",
                    "pre_auction_score": _pick_score(stage_scores, "pre_auction_score", "pre_auction"),
                    "auction_confirmed_score": _pick_score(stage_scores, "auction_confirmed_score", "auction_confirmed"),
                    "open_5m_confirmed_score": _pick_score(stage_scores, "open_5m_confirmed_score", "open_5m"),
                    "official_hot_score": _pick_score(stage_scores, "official_hot_score", "hot_score", "model_score"),
                    "scoring_state": output.get("score_state") or "scored",
                    "recommendation_eligibility": stage_scores.get("recommendation_eligibility") or "research_only",
                    "main_positive_factors_json": stage_scores.get("main_positive_factors") or [],
                    "main_negative_factors_json": stage_scores.get("main_negative_factors") or [],
                    "hard_block_reasons_json": _source_blocks(output),
                    "warning_reasons_json": _source_warnings(output),
                    "score_hash": stable_hash({"task": task.task_code, "output": output}),
                },
                counts,
            )
            return
        if "buy_point_result" in structured:
            buy_point_release_gate = buy_point.get("release_gate") if isinstance(buy_point.get("release_gate"), dict) else {}
            materialized_signal_id = None
            if hot_signal:
                materialized_signal_id = self._materialize_hot_signal(
                    hot_case_id=hot_case_id,
                    hot_cycle_id=hot_cycle_id,
                    symbol=symbol,
                    trade_date=trade_date,
                    as_of_time=as_of_time,
                    hot_signal=hot_signal,
                    release_gate=buy_point_release_gate,
                    case_id_mismatch=owner_case_mismatch,
                    counts=counts,
                )
            self._materialize_hot_buy_point(
                hot_case_id=hot_case_id,
                hot_cycle_id=hot_cycle_id,
                output=output,
                assembly=assembly,
                as_of_time=as_of_time,
                materialized_signal_id=materialized_signal_id,
                case_id_mismatch=owner_case_mismatch,
                counts=counts,
            )
            return
        release_gate = output.get("release_gate") if isinstance(output.get("release_gate"), dict) else {}
        self._insert(
            "decision_hot.hot_release_gate_audit_v1",
            {
                "hot_case_id": hot_case_id,
                "gate_version": release_gate.get("gate_version") or "research_service_release_gate_v1",
                "gate_time": release_gate.get("gate_time") or as_of_time,
                "gate_status": release_gate.get("gate_status") or release_gate.get("release_gate_status") or "unknown",
                "official_signal_allowed": bool(hot_signal.get("is_official_signal") is True),
                "signal_stage": hot_signal.get("signal_stage") or "release_gate",
                "block_reasons_json": release_gate.get("block_reasons") or release_gate.get("hard_block_reasons") or [],
                "warning_reasons_json": release_gate.get("warning_reasons") or release_gate.get("warning_codes") or [],
                "required_evidence_status": release_gate.get("required_evidence_status") or "checked_by_research_service",
            },
            counts,
        )
        if hot_signal:
            self._materialize_hot_signal(
                hot_case_id=hot_case_id,
                hot_cycle_id=hot_cycle_id,
                symbol=symbol,
                trade_date=trade_date,
                as_of_time=as_of_time,
                hot_signal=hot_signal,
                release_gate=release_gate,
                case_id_mismatch=owner_case_mismatch,
                counts=counts,
            )

    def _materialize_hot_signal(
        self,
        *,
        hot_case_id: str,
        hot_cycle_id: str,
        symbol: str | None,
        trade_date: Any,
        as_of_time: Any,
        hot_signal: dict[str, Any],
        release_gate: dict[str, Any],
        case_id_mismatch: bool,
        counts: dict[str, int],
    ) -> str:
        hot_signal_id = None if case_id_mismatch else hot_signal.get("hot_signal_id")
        hot_signal_id = hot_signal_id or _id("hotsig", hot_case_id, hot_signal.get("selected_at") or as_of_time)
        is_official = hot_signal.get("is_official_signal") is True
        is_research_only = hot_signal.get("is_research_only")
        if is_research_only is None:
            is_research_only = not is_official
        self._insert(
            "decision_hot.hot_signal_fact_v1",
            {
                "hot_signal_id": hot_signal_id,
                "hot_case_id": hot_case_id,
                "hot_cycle_id": hot_cycle_id,
                "symbol": hot_signal.get("symbol") or symbol,
                "signal_date": hot_signal.get("signal_date") or trade_date,
                "selected_at": hot_signal.get("selected_at") or as_of_time,
                "decision_time": hot_signal.get("decision_time") or as_of_time,
                "model_version": hot_signal.get("model_version") or "hot_candidates_research_execution_v1",
                "model_score": hot_signal.get("model_score") or hot_signal.get("official_hot_score"),
                "signal_stage": hot_signal.get("signal_stage") or ("official_signal" if is_official else "research_sample"),
                "is_official_signal": is_official,
                "is_research_only": bool(is_research_only),
                "release_gate_status": hot_signal.get("release_gate_status")
                or release_gate.get("gate_status")
                or release_gate.get("release_gate_status")
                or ("passed" if is_official else "blocked"),
                "release_gate_reason": hot_signal.get("release_gate_reason")
                or release_gate.get("block_reasons")
                or release_gate.get("hard_block_reasons")
                or [],
            },
            counts,
        )
        return str(hot_signal_id)

    def _materialize_hot_evidence(self, hot_case_id: str, assembly: ModelPayloadAssembleResponse, counts: dict[str, int]) -> None:
        as_of_time = assembly.as_of_time_utc or assembly.checked_at
        refs = [item.model_dump() for item in assembly.source_refs] or [{"table_name": "research_service", "row_count": 1}]
        for ref in refs[:20]:
            self._insert(
                "decision_hot.hot_evidence_snapshot_v1",
                {
                    "hot_case_id": hot_case_id,
                    "evidence_domain": ref.get("table_name") or "source",
                    "evidence_role": "source_payload",
                    "evidence_status": ref.get("source_quality_status") or "usable",
                    "as_of_time": as_of_time,
                    "available_at": ref.get("available_at") or as_of_time,
                    "captured_at": as_of_time,
                    "source_table": ref.get("table_name"),
                    "source_pk": ref.get("lineage_id") or ref.get("build_batch_id"),
                    "payload_json": ref,
                    "quality_status": ref.get("source_quality_status") or "unknown",
                    "gap_codes": assembly.gap_codes,
                    "payload_hash": stable_hash({"hot_case_id": hot_case_id, "ref": ref}),
                },
                counts,
            )

    def _materialize_hot_buy_point(
        self,
        *,
        hot_case_id: str,
        hot_cycle_id: str,
        output: dict[str, Any],
        assembly: ModelPayloadAssembleResponse,
        as_of_time: Any,
        materialized_signal_id: str | None,
        case_id_mismatch: bool,
        counts: dict[str, int],
    ) -> None:
        buy_point = output.get("buy_point") if isinstance(output.get("buy_point"), dict) else {}
        hot_signal = output.get("hot_signal") if isinstance(output.get("hot_signal"), dict) else {}
        hot_signal_id = materialized_signal_id if case_id_mismatch else None
        hot_signal_id = hot_signal_id or buy_point.get("hot_signal_id") or hot_signal.get("hot_signal_id") or materialized_signal_id
        if not buy_point or not hot_signal_id:
            return
        calculated_at = buy_point.get("calculated_at") or as_of_time
        data_as_of = buy_point.get("data_as_of") or calculated_at
        buy_point_id = None if case_id_mismatch else buy_point.get("buy_point_id")
        buy_point_id = buy_point_id or _id("hot-buy", hot_case_id, calculated_at, assembly.payload_hash)
        self._insert(
            "decision_hot.hot_buy_point_v1",
            {
                "buy_point_id": buy_point_id,
                "hot_signal_id": hot_signal_id,
                "hot_case_id": hot_case_id,
                "hot_cycle_id": hot_cycle_id,
                "adapter_code": buy_point.get("adapter_code") or "hot_candidates_buy_point_adapter",
                "buy_point_version": buy_point.get("buy_point_version")
                or buy_point.get("adapter_version")
                or "hot_candidates_buy_point_adapter_v1",
                "calc_stage": buy_point.get("calc_stage") or "open_5m_vwap_adjusted",
                "reference_entry_price": buy_point.get("reference_entry_price"),
                "entry_price_low": buy_point.get("entry_price_low"),
                "entry_price_high": buy_point.get("entry_price_high"),
                "target_price": buy_point.get("target_price"),
                "invalidation_price": buy_point.get("invalidation_price"),
                "risk_reward_ratio": buy_point.get("risk_reward_ratio"),
                "buy_point_status": buy_point.get("buy_point_status") or "blocked",
                "block_reason": buy_point.get("block_reason"),
                "calculated_at": calculated_at,
                "data_as_of": data_as_of,
                "is_first_valid": bool(buy_point.get("is_first_valid") is True),
                "is_frozen_reference": bool(buy_point.get("is_frozen_reference") is True),
                "input_snapshot_hash": buy_point.get("input_snapshot_hash") or assembly.payload_hash,
                "decision_trace_json": buy_point.get("decision_trace_json") or {},
            },
            counts,
        )

    def _materialize_memory(
        self,
        task: TaskRequirement,
        assembly: ModelPayloadAssembleResponse,
        structured: dict[str, Any],
        counts: dict[str, int],
    ) -> list[str]:
        gaps: list[str] = []
        seed = structured.get("memory_seed") if isinstance(structured.get("memory_seed"), dict) else {}
        entity = structured.get("memory_entity") if isinstance(structured.get("memory_entity"), dict) else {}
        pre_signal = structured.get("pre_signal_case") if isinstance(structured.get("pre_signal_case"), dict) else {}
        release_gate = structured.get("release_gate") if isinstance(structured.get("release_gate"), dict) else {}
        if seed:
            self._insert("decision_memory.memory_seed_v1", _memory_seed_row(seed), counts)
        if entity:
            row = _memory_entity_row(entity)
            if assembly.payload.get("memory_age_days") is None and assembly.payload.get("days_since_first_hot") is None:
                row["memory_age_days"] = None
                row["memory_status"] = "blocked_data_gap"
                gaps.append("source_gap:memory_age_trading_calendar_missing")
            self._insert("decision_memory.memory_entity_v1", row, counts)
        if pre_signal:
            self._insert("decision_memory.memory_pre_signal_case_v1", _memory_pre_signal_row(pre_signal), counts)
            self._insert("decision_memory.memory_score_fact_v1", _memory_score_row(pre_signal), counts)
        if release_gate:
            self._insert("decision_memory.memory_release_gate_audit_v1", _memory_release_row(release_gate), counts)
            if release_gate.get("release_gate_state") == "official_signal_passed" and release_gate.get("memory_signal_id"):
                self._insert("decision_memory.memory_signal_fact_v1", _memory_signal_row(release_gate), counts)
        return gaps

    def _materialize_ambush(
        self,
        task: TaskRequirement,
        assembly: ModelPayloadAssembleResponse,
        structured: dict[str, Any],
        counts: dict[str, int],
    ) -> None:
        phase2 = structured.get("phase2") if isinstance(structured.get("phase2"), dict) else {}
        phase3 = structured.get("phase3") if isinstance(structured.get("phase3"), dict) else {}
        if phase2:
            valley = phase2.get("valley_watch") if isinstance(phase2.get("valley_watch"), dict) else {}
            anchor = phase2.get("effective_turn_anchor") if isinstance(phase2.get("effective_turn_anchor"), dict) else {}
            transition = phase2.get("transition_audit") if isinstance(phase2.get("transition_audit"), dict) else {}
            if valley:
                self._insert("decision_ambush.valley_watch_pool_v1", _ambush_row(valley, assembly, "valley"), counts)
            if anchor:
                self._insert("decision_ambush.effective_turn_anchor_v1", _ambush_row(anchor, assembly, "anchor"), counts)
            if transition:
                self._insert("decision_ambush.ambush_pool_transition_audit_v1", _ambush_transition_row(transition, assembly), counts)
                if transition.get("decision_result") in {"created", "research_only"}:
                    self._insert("decision_ambush.effective_turn_pool_v1", _ambush_pool_row(valley, anchor, transition, assembly), counts)
        if phase3:
            deep = phase3.get("deep_confirmation") if isinstance(phase3.get("deep_confirmation"), dict) else {}
            release = phase3.get("release_gate") if isinstance(phase3.get("release_gate"), dict) else {}
            signal = phase3.get("signal_fact") if isinstance(phase3.get("signal_fact"), dict) else {}
            if deep:
                self._insert("decision_ambush.deep_confirmation_pool_v1", _ambush_row(deep, assembly, "deep"), counts)
                self._insert("decision_ambush.ambush_score_fact_v1", _ambush_score_row(deep, release, assembly), counts)
            if release:
                self._insert("decision_ambush.ambush_release_gate_audit_v1", _ambush_row(release, assembly, "release"), counts)
            if release.get("release_decision") == "passed" and signal.get("signal_state") == "official_signal":
                self._insert("decision_ambush.ambush_signal_fact_v1", _ambush_signal_row(signal, release, assembly), counts)

    def _insert(self, table_name: str, row: dict[str, Any], counts: dict[str, int]) -> None:
        if self.repository.insert_row(table_name, jsonable(row)):
            counts[table_name] += 1


def _memory_seed_row(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_seed_id": seed.get("memory_seed_id"),
        "source_model": seed.get("source_model"),
        "first_source_signal_id": seed.get("first_source_signal_id"),
        "first_source_case_id": seed.get("first_source_case_id"),
        "symbol": seed.get("symbol"),
        "first_selected_date": seed.get("first_selected_date"),
        "first_outcome_label": seed.get("first_outcome_label"),
        "seed_priority": seed.get("seed_priority"),
        "seed_reasons_json": seed.get("seed_reasons") or [],
        "seed_status": seed.get("seed_status"),
        "hard_block_reasons_json": seed.get("hard_block_reasons") or [],
        "source_gap_codes_json": seed.get("source_gap_codes") or [],
        "created_at": seed.get("created_at") or _now(),
        "payload_hash": seed.get("payload_hash") or stable_hash(seed),
    }


def _memory_entity_row(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_entity_id": entity.get("memory_entity_id"),
        "memory_seed_id": entity.get("memory_seed_id"),
        "symbol": entity.get("symbol"),
        "name": entity.get("name"),
        "first_source_model": entity.get("first_source_model"),
        "first_source_signal_id": entity.get("first_source_signal_id"),
        "first_source_case_id": entity.get("first_source_case_id"),
        "first_selected_date": entity.get("first_selected_date"),
        "first_outcome_label": entity.get("first_outcome_label"),
        "memory_status": entity.get("memory_status"),
        "base_ttl_days": entity.get("base_ttl_days"),
        "dynamic_ttl_adjustment_days": entity.get("dynamic_ttl_adjustment_days"),
        "ttl_effective_days": entity.get("ttl_effective_days"),
        "memory_age_days": entity.get("memory_age_days"),
        "decay_score": entity.get("decay_score"),
        "merge_action": entity.get("merge_action"),
        "created_at": entity.get("created_or_updated_at") or _now(),
        "updated_at": entity.get("created_or_updated_at") or _now(),
        "payload_hash": entity.get("payload_hash") or stable_hash(entity),
    }


def _memory_pre_signal_row(pre_signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "pre_signal_case_id": pre_signal.get("pre_signal_case_id"),
        "memory_entity_id": pre_signal.get("memory_entity_id"),
        "symbol": pre_signal.get("symbol"),
        "detected_at": pre_signal.get("detected_at") or _now(),
        "pre_signal_window_start": pre_signal.get("pre_signal_window_start"),
        "pre_signal_window_end": pre_signal.get("pre_signal_window_end"),
        "pre_signal_strength_score": pre_signal.get("pre_signal_strength_score"),
        "pre_signal_types_json": pre_signal.get("pre_signal_types") or [],
        "fake_pre_signal_risk_score": pre_signal.get("fake_pre_signal_risk_score"),
        "ex_ante_event_count": pre_signal.get("ex_ante_event_count") or 0,
        "post_hoc_event_count": pre_signal.get("post_hoc_event_count") or 0,
        "status": pre_signal.get("status"),
        "feature_hash": pre_signal.get("feature_hash") or stable_hash(pre_signal),
        "hard_block_reasons_json": pre_signal.get("hard_block_reasons") or [],
        "source_gap_codes_json": pre_signal.get("source_gap_codes") or [],
        "case_hash": pre_signal.get("case_hash") or stable_hash(pre_signal),
    }


def _memory_score_row(pre_signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "score_id": _id("memscore", pre_signal.get("pre_signal_case_id") or pre_signal.get("memory_entity_id"), pre_signal.get("case_hash")),
        "memory_entity_id": pre_signal.get("memory_entity_id"),
        "activation_case_id": None,
        "symbol": pre_signal.get("symbol"),
        "scored_at": pre_signal.get("detected_at") or _now(),
        "memory_value_score": pre_signal.get("memory_value_score"),
        "pre_signal_score": pre_signal.get("pre_signal_strength_score"),
        "activation_quality_score": None,
        "reason_confidence_score": None,
        "fake_activation_risk_score": pre_signal.get("fake_pre_signal_risk_score"),
        "model_version": pre_signal.get("model_version") or "candidate_memory_research_execution_v1",
        "feature_hash": pre_signal.get("feature_hash") or stable_hash(pre_signal),
        "score_hash": stable_hash({"pre_signal": pre_signal}),
    }


def _memory_release_row(release_gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "release_gate_audit_id": _id("memgate", release_gate.get("memory_entity_id"), release_gate.get("audit_hash")),
        "memory_entity_id": release_gate.get("memory_entity_id"),
        "activation_case_id": release_gate.get("activation_case_id"),
        "memory_signal_id": release_gate.get("memory_signal_id"),
        "symbol": release_gate.get("symbol"),
        "evaluated_at": release_gate.get("evaluated_at") or _now(),
        "release_gate_state": release_gate.get("release_gate_state"),
        "recommendation_eligibility": release_gate.get("recommendation_eligibility"),
        "activation_quality_score": release_gate.get("activation_quality_score"),
        "pre_signal_score": release_gate.get("pre_signal_score"),
        "fake_activation_risk_score": release_gate.get("fake_activation_risk_score"),
        "hard_block_reasons_json": release_gate.get("hard_block_reasons") or [],
        "warning_codes_json": release_gate.get("warning_codes") or [],
        "audit_hash": release_gate.get("audit_hash") or stable_hash(release_gate),
    }


def _memory_signal_row(release_gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_signal_id": release_gate.get("memory_signal_id"),
        "memory_entity_id": release_gate.get("memory_entity_id"),
        "activation_case_id": release_gate.get("activation_case_id"),
        "symbol": release_gate.get("symbol"),
        "published_at": release_gate.get("evaluated_at") or _now(),
        "signal_status": "official_signal",
        "signal_pool": "candidate_memory_official",
        "model_version": release_gate.get("model_version") or "candidate_memory_research_execution_v1",
        "release_gate_audit_hash": release_gate.get("audit_hash") or stable_hash(release_gate),
    }


def _ambush_row(row: dict[str, Any], assembly: ModelPayloadAssembleResponse, kind: str) -> dict[str, Any]:
    payload = dict(row)
    payload.setdefault("symbol", _symbol(assembly))
    payload.setdefault("trade_date", assembly.trade_date)
    payload.setdefault("as_of_trading_day", assembly.trade_date)
    payload.setdefault("calculated_at", assembly.as_of_time_utc or assembly.checked_at)
    payload.setdefault("formula_version", row.get("formula_version") or f"ambush_{kind}_research_execution_v1")
    payload.setdefault("phase3_version", row.get("phase3_version") or "ambush_phase3_research_execution_v1")
    payload.setdefault("price_adjustment_mode", row.get("price_adjustment_mode") or "source_adjusted")
    payload.setdefault("formula_governance_json", row.get("formula_governance") or {"source": "owner_service"})
    payload.setdefault("payload_json", row)
    payload.setdefault("payload_hash", row.get("payload_hash") or stable_hash(row))
    if kind == "valley":
        payload.setdefault("valley_id", _id("valley", payload.get("symbol"), payload.get("as_of_trading_day"), payload.get("payload_hash")))
        payload.setdefault("pool_state", row.get("pool_state") or "research_only")
        payload.setdefault("valley_status", row.get("valley_status") or "data_blocked")
        payload.setdefault("window_days", row.get("window_days") or 60)
    elif kind == "anchor":
        payload.setdefault("turn_anchor_id", _id("turn", payload.get("symbol"), payload.get("as_of_trading_day"), payload.get("payload_hash")))
        payload.setdefault("l1_status", row.get("l1_status") or "rejected")
        payload.setdefault("pool_target", row.get("pool_target") or "none")
    elif kind == "deep":
        payload.setdefault("deep_state", row.get("deep_state") or "blocked_data_gap")
    elif kind == "release":
        payload.setdefault("release_decision", row.get("release_decision") or "blocked")
        payload.setdefault("signal_state", row.get("signal_state") or "not_released")
    return payload


def _ambush_transition_row(transition: dict[str, Any], assembly: ModelPayloadAssembleResponse) -> dict[str, Any]:
    row = dict(transition)
    row.setdefault("transition_id", _id("ambtrans", _symbol(assembly), transition.get("transition_hash")))
    row.setdefault("symbol", _symbol(assembly))
    row.setdefault("from_pool", "valley_watch_pool")
    row.setdefault("to_pool", "effective_turn_pool")
    row.setdefault("decision_result", transition.get("decision_result") or "not_created")
    row.setdefault("trigger_event", "phase2_valley_turn")
    row.setdefault("trigger_as_of_time", assembly.as_of_time_utc or assembly.checked_at)
    row.setdefault("trigger_snapshot_type", "close_confirmed")
    row.setdefault("trigger_feature_json", transition.get("trigger_feature") or {})
    row.setdefault("decision_rule_version", transition.get("decision_rule_version") or "ambush_phase2_research_execution_v1")
    row.setdefault("created_by_job", transition.get("created_by_job") or assembly.run_id)
    row.setdefault("formula_governance_json", transition.get("formula_governance") or {"source": "owner_service"})
    row.setdefault("payload_json", transition)
    row.setdefault("transition_hash", transition.get("transition_hash") or stable_hash(transition))
    row.setdefault("calculated_at", assembly.as_of_time_utc or assembly.checked_at)
    return row


def _ambush_pool_row(valley: dict[str, Any], anchor: dict[str, Any], transition: dict[str, Any], assembly: ModelPayloadAssembleResponse) -> dict[str, Any]:
    decision = transition.get("decision_result")
    return {
        "pool_item_id": _id("ambpool", _symbol(assembly), transition.get("transition_hash")),
        "symbol": _symbol(assembly),
        "valley_id": valley.get("valley_id"),
        "turn_anchor_id": anchor.get("turn_anchor_id"),
        "as_of_trading_day": valley.get("as_of_trading_day") or anchor.get("as_of_trading_day") or assembly.trade_date,
        "pool_state": "active" if decision == "created" else "research_only",
        "pool_entered_at": assembly.as_of_time_utc or assembly.checked_at,
        "anchor_type": anchor.get("anchor_type"),
        "effective_turn_anchor_day": anchor.get("effective_turn_anchor_day"),
        "turn_freshness_score": anchor.get("turn_freshness_score"),
        "effective_turn_score": anchor.get("effective_turn_score"),
        "valley_maturity_score": valley.get("valley_maturity_score"),
        "false_rebound_risk": valley.get("false_rebound_risk") or anchor.get("false_rebound_risk"),
        "next_required_confirmation_json": ["phase3_deep_confirmation"],
        "invalidation_conditions_json": [],
        "source_gap_codes_json": sorted(set((valley.get("source_gap_codes") or []) + (anchor.get("source_gap_codes") or []))),
        "formula_version": anchor.get("formula_version") or valley.get("formula_version") or "ambush_phase2_research_execution_v1",
        "payload_json": {"valley_watch": valley, "effective_turn_anchor": anchor, "transition_audit": transition},
        "payload_hash": stable_hash({"valley": valley, "anchor": anchor, "transition": transition}),
    }


def _ambush_score_row(deep: dict[str, Any], release: dict[str, Any], assembly: ModelPayloadAssembleResponse) -> dict[str, Any]:
    return {
        "symbol": deep.get("symbol") or _symbol(assembly),
        "trade_date": deep.get("trade_date") or assembly.trade_date,
        "calculated_at": deep.get("calculated_at") or assembly.as_of_time_utc or assembly.checked_at,
        "formula_version": deep.get("formula_version") or release.get("formula_version") or "ambush_phase3_research_execution_v1",
        "valley_maturity_score": deep.get("valley_maturity_score"),
        "effective_turn_score": deep.get("effective_turn_score"),
        "l2_structure_score": deep.get("l2_structure_score"),
        "l3_capital_volume_score": deep.get("l3_capital_volume_score"),
        "l4_environment_score": deep.get("l4_environment_score"),
        "false_rebound_risk": deep.get("false_rebound_risk"),
        "tradability_score": deep.get("tradability_score"),
        "ambush_score": deep.get("ambush_score") or release.get("ambush_score"),
        "source_gap_codes_json": deep.get("source_gap_codes") or [],
        "formula_governance_json": deep.get("formula_governance") or {"source": "owner_service"},
        "payload_hash": stable_hash({"deep": deep, "release": release}),
    }


def _ambush_signal_row(signal: dict[str, Any], release: dict[str, Any], assembly: ModelPayloadAssembleResponse) -> dict[str, Any]:
    row = dict(signal)
    row.setdefault("signal_id", _id("ambsig", _symbol(assembly), row.get("payload_hash")))
    row.setdefault("symbol", _symbol(assembly))
    row.setdefault("trade_date", assembly.trade_date)
    row.setdefault("published_at", assembly.as_of_time_utc or assembly.checked_at)
    row.setdefault("signal_state", "official_signal")
    row.setdefault("release_gate_hash", release.get("payload_hash"))
    row.setdefault("formula_version", release.get("formula_version") or "ambush_phase3_research_execution_v1")
    row.setdefault("evidence_refs_json", release.get("evidence_refs") or [])
    row.setdefault("payload_hash", stable_hash({"signal": signal, "release": release}))
    return row


def _hot_upstream_case(assembly: ModelPayloadAssembleResponse) -> dict[str, Any]:
    return _first_hot_upstream_row(assembly, "decision_hot.hot_decision_case_v1")


def _first_hot_upstream_row(assembly: ModelPayloadAssembleResponse, table_name: str) -> dict[str, Any]:
    upstream = assembly.payload.get("upstream_model_facts") if isinstance(assembly.payload, dict) else None
    if not isinstance(upstream, dict):
        return {}
    table_rows = upstream.get(table_name)
    if isinstance(table_rows, dict):
        for symbol in assembly.symbols:
            rows = table_rows.get(symbol) or table_rows.get(str(symbol).upper()) or table_rows.get(str(symbol).lower())
            row = _first_dict(rows)
            if row:
                return row
        for rows in table_rows.values():
            row = _first_dict(rows)
            if row:
                return row
    return _first_dict(table_rows)


def _first_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _hot_case_id_mismatch(canonical_hot_case_id: Any, *rows: dict[str, Any]) -> bool:
    if canonical_hot_case_id in (None, ""):
        return False
    canonical = str(canonical_hot_case_id)
    for row in rows:
        owner_case_id = row.get("hot_case_id") if isinstance(row, dict) else None
        if owner_case_id not in (None, "") and str(owner_case_id) != canonical:
            return True
    return False


def _source_blocks(output: dict[str, Any]) -> list[Any]:
    audit = output.get("source_visibility_audit") if isinstance(output.get("source_visibility_audit"), dict) else {}
    return audit.get("hard_block_codes") or output.get("hard_block_reasons") or []


def _source_warnings(output: dict[str, Any]) -> list[Any]:
    audit = output.get("source_visibility_audit") if isinstance(output.get("source_visibility_audit"), dict) else {}
    return audit.get("warning_codes") or output.get("warning_codes") or []


def _pick_score(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values:
            return values[key]
    return None


def _symbol(assembly: ModelPayloadAssembleResponse) -> str:
    return (assembly.symbols[0] if assembly.symbols else assembly.payload.get("symbol") or "").upper()


def _id(prefix: str, *parts: Any) -> str:
    cleaned = [str(part) for part in parts if part not in (None, "")]
    if not cleaned:
        return new_id(prefix)
    return f"{prefix}-{stable_hash({'parts': cleaned})[:24]}"


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner_response_model_version(structured: dict[str, Any], *, default: str) -> str:
    _ = structured
    return default
