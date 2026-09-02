from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from data_inspector_service.contracts import DomainContract
from data_inspector_service.schemas import (
    InspectionGapOut,
    InspectionGapRecordOut,
    InspectionRunOut,
    InspectionSubjectOut,
    RemediationTaskOut,
)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


class DataInspectorRepository:
    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url

    def ready(self) -> dict[str, Any]:
        if not self.database_url:
            return {"status": "degraded", "database_url_configured": False}
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                row = conn.execute("select 1 as ok").fetchone()
            return {"status": "ready", "database_url_configured": True, "select_1": row["ok"] == 1}
        except Exception as exc:
            return {"status": "not_ready", "database_url_configured": True, "error": str(exc)}

    def sync_domain_contracts(self, contracts: list[DomainContract]) -> int:
        if not self.database_url:
            return 0
        accepted = 0
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                for contract in contracts:
                    conn.execute(
                        """
                        insert into decision.data_inspection_domain_contract (
                            domain_code, business_line, target_table, grain,
                            required_level, default_severity, blocks_scoring,
                            blocks_publish, replay_safe, provider_lineage_required,
                            contract_json, updated_at
                        )
                        values (
                            %(domain_code)s, %(business_line)s, %(target_table)s, %(grain)s,
                            %(required_level)s, %(default_severity)s, %(blocks_scoring)s,
                            %(blocks_publish)s, %(replay_safe)s, %(provider_lineage_required)s,
                            %(contract_json)s, now()
                        )
                        on conflict (business_line, domain_code) do update set
                            target_table = excluded.target_table,
                            grain = excluded.grain,
                            required_level = excluded.required_level,
                            default_severity = excluded.default_severity,
                            blocks_scoring = excluded.blocks_scoring,
                            blocks_publish = excluded.blocks_publish,
                            replay_safe = excluded.replay_safe,
                            provider_lineage_required = excluded.provider_lineage_required,
                            contract_json = excluded.contract_json,
                            updated_at = now()
                        """,
                        {
                            **contract.to_dict(),
                            "contract_json": Jsonb({"description": contract.description}),
                        },
                    )
                    accepted += 1
        return accepted

    def persist_run(self, run: InspectionRunOut) -> InspectionRunOut:
        if not self.database_url:
            run.warning_codes.append("inspection_not_persisted:no_database_url")
            return run
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                run_row = conn.execute(
                    """
                    insert into decision.data_inspection_run (
                        scope, as_of_trading_day, lookback_days, status,
                        requested_subject_count, inspected_subject_count,
                        gap_count, p0_gap_count, p1_gap_count,
                        run_contract_json, started_at, finished_at
                    )
                    values (
                        %(scope)s, %(as_of_trading_day)s, %(lookback_days)s, %(status)s,
                        %(requested_subject_count)s, %(inspected_subject_count)s,
                        %(gap_count)s, %(p0_gap_count)s, %(p1_gap_count)s,
                        %(run_contract_json)s, %(started_at)s, %(finished_at)s
                    )
                    returning run_id
                    """,
                    {
                        "scope": run.scope,
                        "as_of_trading_day": run.as_of_trading_day,
                        "lookback_days": run.lookback_days,
                        "status": run.status,
                        "requested_subject_count": run.requested_subject_count,
                        "inspected_subject_count": run.inspected_subject_count,
                        "gap_count": run.gap_count,
                        "p0_gap_count": run.p0_gap_count,
                        "p1_gap_count": run.p1_gap_count,
                        "run_contract_json": Jsonb(
                            _jsonable(
                                {
                                    "contract_kind": run.contract_kind,
                                    "inspection_version": run.inspection_version,
                                    "warning_codes": run.warning_codes,
                                    "time_semantics": run.time_semantics,
                                    "guardrails": run.guardrails,
                                    "publish_due_status": run.publish_due_status,
                                }
                            )
                        ),
                        "started_at": run.started_at,
                        "finished_at": run.finished_at,
                    },
                ).fetchone()
                run.run_id = int(run_row["run_id"])
                subject_by_symbol: dict[str, InspectionSubjectOut] = {}
                for subject in run.subjects:
                    subject_row = conn.execute(
                        """
                        insert into decision.data_inspection_subject (
                            run_id, instrument_id, symbol_snapshot, scope,
                            expected_domain_count, observed_domain_count, missing_domain_count,
                            fine_time_gap_count, coarse_time_gap_count, inspection_status,
                            completeness_score, summary_json
                        )
                        values (
                            %(run_id)s, %(instrument_id)s, %(symbol_snapshot)s, %(scope)s,
                            %(expected_domain_count)s, %(observed_domain_count)s, %(missing_domain_count)s,
                            %(fine_time_gap_count)s, %(coarse_time_gap_count)s, %(inspection_status)s,
                            %(completeness_score)s, %(summary_json)s
                        )
                        returning subject_id
                        """,
                        {
                            "run_id": run.run_id,
                            "instrument_id": subject.instrument_id,
                            "symbol_snapshot": subject.symbol,
                            "scope": subject.scope,
                            "expected_domain_count": subject.expected_domain_count,
                            "observed_domain_count": subject.observed_domain_count,
                            "missing_domain_count": subject.missing_domain_count,
                            "fine_time_gap_count": subject.fine_time_gap_count,
                            "coarse_time_gap_count": subject.coarse_time_gap_count,
                            "inspection_status": subject.inspection_status,
                            "completeness_score": subject.completeness_score,
                            "summary_json": Jsonb(_jsonable(subject.summary)),
                        },
                    ).fetchone()
                    subject.subject_id = int(subject_row["subject_id"])
                    subject_by_symbol[subject.symbol] = subject
                fallback_subject = run.subjects[0] if run.subjects else None
                for gap in run.gaps:
                    subject = subject_by_symbol.get(gap.symbol) or fallback_subject
                    if subject is None:
                        continue
                    gap.subject_id = subject.subject_id
                    gap_row = conn.execute(
                        """
                        insert into decision.data_inspection_gap (
                            run_id, subject_id, instrument_id, symbol_snapshot,
                            gap_type, domain_code, target_table, severity, trading_day,
                            gap_start_at, gap_end_at, missing_count, expected_count,
                            observed_count, blocks_scoring, blocks_publish, replay_safe,
                            provider_lineage_required, remediation_status, details_json
                        )
                        values (
                            %(run_id)s, %(subject_id)s, %(instrument_id)s, %(symbol_snapshot)s,
                            %(gap_type)s, %(domain_code)s, %(target_table)s, %(severity)s, %(trading_day)s,
                            %(gap_start_at)s, %(gap_end_at)s, %(missing_count)s, %(expected_count)s,
                            %(observed_count)s, %(blocks_scoring)s, %(blocks_publish)s, %(replay_safe)s,
                            %(provider_lineage_required)s, %(remediation_status)s, %(details_json)s
                        )
                        returning gap_id
                        """,
                        {
                            "run_id": run.run_id,
                            "subject_id": gap.subject_id,
                            "instrument_id": gap.instrument_id,
                            "symbol_snapshot": gap.symbol,
                            "gap_type": gap.gap_type,
                            "domain_code": gap.domain_code,
                            "target_table": gap.target_table,
                            "severity": gap.severity,
                            "trading_day": gap.trading_day,
                            "gap_start_at": gap.gap_start_at,
                            "gap_end_at": gap.gap_end_at,
                            "missing_count": gap.missing_count,
                            "expected_count": gap.expected_count,
                            "observed_count": gap.observed_count,
                            "blocks_scoring": gap.blocks_scoring,
                            "blocks_publish": gap.blocks_publish,
                            "replay_safe": gap.replay_safe,
                            "provider_lineage_required": gap.provider_lineage_required,
                            "remediation_status": gap.remediation_status,
                            "details_json": Jsonb(_jsonable(gap.details)),
                        },
                    ).fetchone()
                    gap.gap_id = int(gap_row["gap_id"])
                for task in run.remediation_tasks:
                    if task.gap_id is None and run.gaps:
                        matched = next((gap for gap in run.gaps if gap.domain_code == task.request_payload.get("domain_code")), None)
                        task.gap_id = matched.gap_id if matched is not None else run.gaps[0].gap_id
                    if task.gap_id is None:
                        continue
                    task_row = conn.execute(
                        """
                        insert into decision.data_inspection_remediation_task (
                            run_id, gap_id, action_type, owner_service, priority,
                            provider_candidates_json, request_payload_json, status
                        )
                        values (
                            %(run_id)s, %(gap_id)s, %(action_type)s, %(owner_service)s, %(priority)s,
                            %(provider_candidates_json)s, %(request_payload_json)s, %(status)s
                        )
                        returning task_id
                        """,
                        {
                            "run_id": run.run_id,
                            "gap_id": task.gap_id,
                            "action_type": task.action_type,
                            "owner_service": task.owner_service,
                            "priority": task.priority,
                            "provider_candidates_json": Jsonb(_jsonable(task.provider_candidates)),
                            "request_payload_json": Jsonb(_jsonable(task.request_payload)),
                            "status": task.status,
                        },
                    ).fetchone()
                    task.task_id = int(task_row["task_id"])
        return run

    def latest_run_summary(
        self,
        *,
        scope: str | None = None,
        as_of_trading_day: date | str | None = None,
    ) -> dict[str, Any] | None:
        if not self.database_url:
            return None
        query = "select * from decision.data_inspection_run"
        params: dict[str, Any] = {}
        where: list[str] = []
        if scope:
            where.append("scope = %(scope)s")
            params["scope"] = scope
        if as_of_trading_day:
            where.append("as_of_trading_day = %(as_of_trading_day)s")
            params["as_of_trading_day"] = as_of_trading_day
        if where:
            query += " where " + " and ".join(where)
        query += " order by started_at desc, run_id desc limit 1"
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            return conn.execute(query, params).fetchone()

    def list_gap_records(
        self,
        *,
        run_id: int | None = None,
        severity: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[InspectionGapRecordOut]:
        if not self.database_url:
            return []
        where: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if run_id is not None:
            where.append("run_id = %(run_id)s")
            params["run_id"] = run_id
        if severity is not None:
            where.append("severity = %(severity)s")
            params["severity"] = severity
        if symbol is not None:
            where.append("symbol_snapshot = %(symbol)s")
            params["symbol"] = symbol
        query = "select *, symbol_snapshot as symbol from decision.data_inspection_gap"
        if where:
            query += " where " + " and ".join(where)
        query += " order by created_at desc, gap_id desc limit %(limit)s"
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(query, params).fetchall()
        return [InspectionGapRecordOut.model_validate(dict(row)) for row in rows]

    def source_table_counts(self) -> dict[str, int]:
        if not self.database_url:
            return {}
        tables = [
            ("source.daily_bar_v1", "source_daily_bar_v1"),
            ("source.adjusted_daily_bar_v1", "source_adjusted_daily_bar_v1"),
            ("source.stock_moneyflow_daily_v1", "source_stock_moneyflow_daily_v1"),
            ("source.event_news_v1", "source_event_news_v1"),
            ("governance.source_lineage_v1", "governance_source_lineage_v1"),
            ("decision_t_relay.t_board_day1_candidate_v1", "decision_t_relay_day1_candidate_v1"),
            ("decision_t_relay.t_board_day2_watch_snapshot_v1", "decision_t_relay_day2_watch_snapshot_v1"),
            ("decision_t_relay.t_board_day2_entry_trigger_v1", "decision_t_relay_day2_entry_trigger_v1"),
            ("decision_t_relay.t_board_post_entry_monitor_v1", "decision_t_relay_post_entry_monitor_v1"),
            ("decision_t_relay.t_board_day3_exit_decision_v1", "decision_t_relay_day3_exit_decision_v1"),
            ("decision_t_relay.t_board_outcome_label_v1", "decision_t_relay_outcome_label_v1"),
            ("decision_t_relay.t_board_game_hypothesis_snapshot_v1", "decision_t_relay_game_hypothesis_snapshot_v1"),
            ("research_t_relay.t_board_research_sample_v1", "research_t_relay_research_sample_v1"),
        ]
        counts: dict[str, int] = {}
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            for table_name, key in tables:
                schema, table = table_name.split(".", 1)
                exists = conn.execute(
                    """
                    select 1
                    from information_schema.tables
                    where table_schema = %(schema)s and table_name = %(table)s
                    """,
                    {"schema": schema, "table": table},
                ).fetchone()
                if not exists:
                    counts[key] = 0
                    continue
                row = conn.execute(f"select count(*) as count from {table_name}").fetchone()
                counts[key] = int(row["count"])
        return counts

    def lineage_duplicate_summary(self, *, limit: int = 20) -> dict[str, Any]:
        if not self.database_url:
            return {"duplicate_group_count": 0, "duplicate_rows": [], "database_url_configured": False}
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                with duplicate_groups as (
                    select
                        source_table_name,
                        source_pk,
                        canonical_field_name,
                        provider,
                        api_name,
                        raw_table_name,
                        raw_id,
                        count(*) as duplicate_count
                    from governance.source_lineage_v1
                    group by
                        source_table_name,
                        source_pk,
                        canonical_field_name,
                        provider,
                        api_name,
                        raw_table_name,
                        raw_id
                    having count(*) > 1
                )
                select *
                from duplicate_groups
                order by duplicate_count desc, source_table_name, source_pk, canonical_field_name
                limit %(limit)s
                """,
                {"limit": limit},
            ).fetchall()
            count_row = conn.execute(
                """
                with duplicate_groups as (
                    select 1
                    from governance.source_lineage_v1
                    group by
                        source_table_name,
                        source_pk,
                        canonical_field_name,
                        provider,
                        api_name,
                        raw_table_name,
                        raw_id
                    having count(*) > 1
                )
                select count(*) as count from duplicate_groups
                """
            ).fetchone()
        return {
            "duplicate_group_count": int(count_row["count"]),
            "duplicate_rows": [dict(row) for row in rows],
            "database_url_configured": True,
        }
