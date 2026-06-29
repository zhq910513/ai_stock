from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from research_center_service.schemas import (
    LibraryMemberCreate,
    ManualLabelCreate,
    ReviewCreate,
    ValleyChartCaseCreate,
)


class ResearchRepositoryError(RuntimeError):
    pass


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


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ResearchCenterRepository:
    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url

    def ready(self) -> dict[str, Any]:
        if not self.database_url:
            return {"status": "degraded", "database_url_configured": False}
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                row = conn.execute(
                    """
                    select exists (
                        select 1
                        from information_schema.tables
                        where table_schema = 'research_ambush'
                          and table_name = 'ambush_valley_chart_case_v1'
                    ) as has_valley_chart_table
                    """
                ).fetchone()
            table_ready = bool(row["has_valley_chart_table"])
            return {
                "status": "ready" if table_ready else "not_ready",
                "database_url_configured": True,
                "research_ambush_schema_ready": table_ready,
            }
        except Exception as exc:
            return {"status": "not_ready", "database_url_configured": True, "error": str(exc)}

    def list_taxonomy(self, *, label_mode: str | None = None, enabled_only: bool = True) -> list[dict[str, Any]]:
        where = ["(%(enabled_only)s = false or enabled = true)"]
        params: dict[str, Any] = {"enabled_only": enabled_only}
        if label_mode:
            where.append("(allowed_label_mode = 'both' or allowed_label_mode = %(label_mode)s)")
            params["label_mode"] = label_mode
        return self._fetch_all(
            f"""
            select taxonomy_id, tag_group, tag_code, tag_name, tag_description,
                   allowed_label_mode, is_positive_signal, is_negative_signal,
                   is_hard_negative_signal, is_training_eligible, enabled, display_order
            from research_ambush.ambush_valley_label_taxonomy_v1
            where {' and '.join(where)}
            order by display_order, tag_group, tag_code
            """,
            params,
        )

    def list_cases(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: dict[str, Any] = {"limit": limit}
        if status:
            clauses.append("c.case_status = %(status)s")
            params["status"] = status
        if symbol:
            clauses.append("c.canonical_symbol = %(symbol)s")
            params["symbol"] = symbol.strip().upper()
        where = f"where {' and '.join(clauses)}" if clauses else ""
        return self._fetch_all(
            f"""
            select c.*,
                   latest.manual_label_id as latest_label_id,
                   latest.label_mode as latest_label_mode,
                   latest.sample_role_label as latest_sample_role_label,
                   latest.outcome_label as latest_outcome_label,
                   latest.manual_label_confidence as latest_label_confidence,
                   review.review_status as review_status,
                   library.library_role as library_role
            from research_ambush.ambush_valley_chart_case_v1 c
            left join lateral (
                select manual_label_id, label_mode, sample_role_label, outcome_label, manual_label_confidence
                from research_ambush.ambush_valley_manual_label_v1 ml
                where ml.chart_case_id = c.chart_case_id
                order by ml.created_at desc
                limit 1
            ) latest on true
            left join lateral (
                select review_status
                from research_ambush.ambush_valley_label_review_v1 r
                where r.chart_case_id = c.chart_case_id
                order by r.created_at desc
                limit 1
            ) review on true
            left join lateral (
                select library_role
                from research_ambush.ambush_valley_pattern_library_member_v1 lm
                where lm.chart_case_id = c.chart_case_id
                order by lm.created_at desc
                limit 1
            ) library on true
            {where}
            order by c.updated_at desc, c.created_at desc
            limit %(limit)s
            """,
            params,
        )

    def get_case(self, chart_case_id: str) -> dict[str, Any] | None:
        rows = self._fetch_all(
            """
            select *
            from research_ambush.ambush_valley_chart_case_v1
            where chart_case_id = %(chart_case_id)s
            """,
            {"chart_case_id": chart_case_id},
        )
        if not rows:
            return None
        case = rows[0]
        case["labels"] = self._fetch_all(
            """
            select *
            from research_ambush.ambush_valley_manual_label_v1
            where chart_case_id = %(chart_case_id)s
            order by created_at desc
            """,
            {"chart_case_id": chart_case_id},
        )
        label_ids = [row["manual_label_id"] for row in case["labels"]]
        case["label_tags"] = []
        if label_ids:
            case["label_tags"] = self._fetch_all(
                """
                select *
                from research_ambush.ambush_valley_manual_label_tag_v1
                where manual_label_id = any(%(label_ids)s)
                order by created_at
                """,
                {"label_ids": label_ids},
            )
        case["reviews"] = self._fetch_all(
            """
            select *
            from research_ambush.ambush_valley_label_review_v1
            where chart_case_id = %(chart_case_id)s
            order by created_at desc
            """,
            {"chart_case_id": chart_case_id},
        )
        case["library_members"] = self._fetch_all(
            """
            select *
            from research_ambush.ambush_valley_pattern_library_member_v1
            where chart_case_id = %(chart_case_id)s
            order by created_at desc
            """,
            {"chart_case_id": chart_case_id},
        )
        return case

    def create_case(self, payload: ValleyChartCaseCreate) -> dict[str, Any]:
        chart_case_id = payload.chart_case_id or _new_id("ambush_valley_case")
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    insert into research_ambush.ambush_valley_chart_case_v1 (
                        chart_case_id, canonical_symbol, stock_name, case_trade_date,
                        case_source, case_status, label_mode_allowed, as_of_date,
                        valley_low_date, turn_anchor_date, source_data_version,
                        model_version, feature_version, source_gap_codes,
                        dynamic_gap_codes, daily_bar_payload, weekly_bar_payload,
                        automatic_feature_payload, decision_ref, created_by
                    )
                    values (
                        %(chart_case_id)s, %(canonical_symbol)s, %(stock_name)s, %(case_trade_date)s,
                        %(case_source)s, %(case_status)s, %(label_mode_allowed)s, %(as_of_date)s,
                        %(valley_low_date)s, %(turn_anchor_date)s, %(source_data_version)s,
                        %(model_version)s, %(feature_version)s, %(source_gap_codes)s,
                        %(dynamic_gap_codes)s, %(daily_bar_payload)s, %(weekly_bar_payload)s,
                        %(automatic_feature_payload)s, %(decision_ref)s, %(created_by)s
                    )
                    on conflict (chart_case_id) do update set
                        canonical_symbol = excluded.canonical_symbol,
                        stock_name = excluded.stock_name,
                        case_trade_date = excluded.case_trade_date,
                        case_source = excluded.case_source,
                        case_status = excluded.case_status,
                        label_mode_allowed = excluded.label_mode_allowed,
                        as_of_date = excluded.as_of_date,
                        valley_low_date = excluded.valley_low_date,
                        turn_anchor_date = excluded.turn_anchor_date,
                        source_data_version = excluded.source_data_version,
                        model_version = excluded.model_version,
                        feature_version = excluded.feature_version,
                        source_gap_codes = excluded.source_gap_codes,
                        dynamic_gap_codes = excluded.dynamic_gap_codes,
                        daily_bar_payload = excluded.daily_bar_payload,
                        weekly_bar_payload = excluded.weekly_bar_payload,
                        automatic_feature_payload = excluded.automatic_feature_payload,
                        decision_ref = excluded.decision_ref,
                        updated_at = now()
                    returning *
                    """,
                    {
                        **payload.model_dump(),
                        "chart_case_id": chart_case_id,
                        "source_gap_codes": Jsonb(payload.source_gap_codes),
                        "dynamic_gap_codes": Jsonb(payload.dynamic_gap_codes),
                        "daily_bar_payload": Jsonb(_jsonable(payload.daily_bar_payload)),
                        "weekly_bar_payload": Jsonb(_jsonable(payload.weekly_bar_payload)),
                        "automatic_feature_payload": Jsonb(_jsonable(payload.automatic_feature_payload)),
                        "decision_ref": Jsonb(_jsonable(payload.decision_ref)),
                    },
                ).fetchone()
        return dict(row)

    def create_label(self, chart_case_id: str, payload: ManualLabelCreate) -> dict[str, Any]:
        case = self._case_or_raise(chart_case_id)
        if case["label_mode_allowed"] != "both" and case["label_mode_allowed"] != payload.label_mode:
            raise ResearchRepositoryError("该样本不允许当前标注模式。")
        taxonomy = {row["tag_code"]: row for row in self.list_taxonomy(enabled_only=True)}
        for tag_code in payload.tags:
            tag = taxonomy.get(tag_code)
            if tag is None:
                raise ResearchRepositoryError(f"未知标注项：{tag_code}")
            if tag["allowed_label_mode"] not in ("both", payload.label_mode):
                raise ResearchRepositoryError("当前标注模式不能使用事后复盘标签。")
        if payload.label_mode == "as_of" and payload.outcome_label:
            raise ResearchRepositoryError("当时可见模式不能填写结果标签。")
        manual_label_id = payload.manual_label_id or _new_id("ambush_valley_label")
        with self._connect() as conn:
            with conn.transaction():
                label = conn.execute(
                    """
                    insert into research_ambush.ambush_valley_manual_label_v1 (
                        manual_label_id, chart_case_id, labeler_id, labeler_role, label_mode,
                        valley_structure_label, turn_timing_label, sample_role_label, outcome_label,
                        manual_label_confidence, manual_label_note, visible_feature_boundary
                    )
                    values (
                        %(manual_label_id)s, %(chart_case_id)s, %(labeler_id)s, %(labeler_role)s, %(label_mode)s,
                        %(valley_structure_label)s, %(turn_timing_label)s, %(sample_role_label)s, %(outcome_label)s,
                        %(manual_label_confidence)s, %(manual_label_note)s, %(visible_feature_boundary)s
                    )
                    returning *
                    """,
                    {
                        **payload.model_dump(exclude={"tags"}),
                        "manual_label_id": manual_label_id,
                        "chart_case_id": chart_case_id,
                        "visible_feature_boundary": Jsonb(_jsonable(payload.visible_feature_boundary)),
                    },
                ).fetchone()
                tag_rows = []
                for tag_code in payload.tags:
                    tag = taxonomy[tag_code]
                    tag_row = conn.execute(
                        """
                        insert into research_ambush.ambush_valley_manual_label_tag_v1 (
                            manual_label_tag_id, manual_label_id, tag_group, tag_code, tag_value
                        )
                        values (
                            %(manual_label_tag_id)s, %(manual_label_id)s, %(tag_group)s, %(tag_code)s, 'true'
                        )
                        returning *
                        """,
                        {
                            "manual_label_tag_id": _new_id("ambush_valley_tag"),
                            "manual_label_id": manual_label_id,
                            "tag_group": tag["tag_group"],
                            "tag_code": tag_code,
                        },
                    ).fetchone()
                    tag_rows.append(dict(tag_row))
                conn.execute(
                    """
                    update research_ambush.ambush_valley_chart_case_v1
                    set case_status = case when case_status = 'pending_labeling' then 'labeled' else case_status end,
                        updated_at = now()
                    where chart_case_id = %(chart_case_id)s
                    """,
                    {"chart_case_id": chart_case_id},
                )
        result = dict(label)
        result["tag_rows"] = tag_rows
        result["tags"] = payload.tags
        return result

    def create_review(self, chart_case_id: str, payload: ReviewCreate) -> dict[str, Any]:
        self._case_or_raise(chart_case_id)
        review_id = payload.review_id or _new_id("ambush_valley_review")
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    insert into research_ambush.ambush_valley_label_review_v1 (
                        review_id, chart_case_id, manual_label_id, reviewer_id, review_status,
                        review_comment, final_sample_role_label, final_outcome_label, final_label_confidence
                    )
                    values (
                        %(review_id)s, %(chart_case_id)s, %(manual_label_id)s, %(reviewer_id)s, %(review_status)s,
                        %(review_comment)s, %(final_sample_role_label)s, %(final_outcome_label)s, %(final_label_confidence)s
                    )
                    returning *
                    """,
                    {**payload.model_dump(), "review_id": review_id, "chart_case_id": chart_case_id},
                ).fetchone()
                if payload.review_status == "approved":
                    conn.execute(
                        """
                        update research_ambush.ambush_valley_chart_case_v1
                        set case_status = 'approved', updated_at = now()
                        where chart_case_id = %(chart_case_id)s
                        """,
                        {"chart_case_id": chart_case_id},
                    )
        return dict(row)

    def create_library_member(self, chart_case_id: str, payload: LibraryMemberCreate) -> dict[str, Any]:
        self._case_or_raise(chart_case_id)
        library_member_id = payload.library_member_id or _new_id("ambush_valley_member")
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    insert into research_ambush.ambush_valley_pattern_library_member_v1 (
                        library_member_id, chart_case_id, manual_label_id, library_role, pattern_family,
                        training_split, approved_by, approved_at, shape_signature_id, feature_snapshot_id
                    )
                    values (
                        %(library_member_id)s, %(chart_case_id)s, %(manual_label_id)s, %(library_role)s, %(pattern_family)s,
                        %(training_split)s, %(approved_by)s, case when %(approved_by)s is null then null else now() end,
                        %(shape_signature_id)s, %(feature_snapshot_id)s
                    )
                    returning *
                    """,
                    {**payload.model_dump(), "library_member_id": library_member_id, "chart_case_id": chart_case_id},
                ).fetchone()
        return dict(row)

    def _case_or_raise(self, chart_case_id: str) -> dict[str, Any]:
        case = self.get_case(chart_case_id)
        if case is None:
            raise ResearchRepositoryError("低谷图库样本不存在。")
        return case

    def _fetch_all(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(query, params or {}).fetchall()
        return [dict(row) for row in rows]

    def _connect(self):
        if not self.database_url:
            raise ResearchRepositoryError("研究中心数据库未配置。")
        return psycopg.connect(self.database_url, row_factory=dict_row)
