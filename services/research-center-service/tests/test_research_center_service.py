from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient

import research_center_service.api as api_module
from research_center_service.main import app
from research_center_service.repository import ResearchRepositoryError
from research_center_service.schemas import (
    LibraryMemberCreate,
    ManualLabelCreate,
    ReviewCreate,
    ValleyChartCaseCreate,
)


class MemoryResearchRepository:
    def __init__(self) -> None:
        self.cases: dict[str, dict[str, Any]] = {}
        self.labels: dict[str, list[dict[str, Any]]] = {}
        self.reviews: dict[str, list[dict[str, Any]]] = {}
        self.members: dict[str, list[dict[str, Any]]] = {}
        self.taxonomy = [
            {
                "taxonomy_id": "taxonomy:structure:mature_valley",
                "tag_group": "structure",
                "tag_code": "MATURE_VALLEY",
                "tag_name": "低谷成熟",
                "tag_description": "低谷成熟",
                "allowed_label_mode": "both",
                "is_positive_signal": True,
                "is_negative_signal": False,
                "is_hard_negative_signal": False,
                "is_training_eligible": True,
                "enabled": True,
                "display_order": 10,
            },
            {
                "taxonomy_id": "taxonomy:risk:false_rebound",
                "tag_group": "risk",
                "tag_code": "FALSE_REBOUND",
                "tag_name": "假反弹",
                "tag_description": "只允许事后复盘",
                "allowed_label_mode": "outcome_review",
                "is_positive_signal": False,
                "is_negative_signal": True,
                "is_hard_negative_signal": True,
                "is_training_eligible": True,
                "enabled": True,
                "display_order": 80,
            },
        ]

    def ready(self) -> dict[str, Any]:
        return {"status": "ready", "database_url_configured": False, "research_ambush_schema_ready": True}

    def list_taxonomy(self, *, label_mode: str | None = None, enabled_only: bool = True) -> list[dict[str, Any]]:
        rows = list(self.taxonomy)
        if label_mode:
            rows = [row for row in rows if row["allowed_label_mode"] in ("both", label_mode)]
        return rows

    def create_case(self, payload: ValleyChartCaseCreate) -> dict[str, Any]:
        chart_case_id = payload.chart_case_id or "case_1"
        row = {**payload.model_dump(), "chart_case_id": chart_case_id, "created_at": None, "updated_at": None}
        self.cases[chart_case_id] = row
        return row

    def list_cases(self, *, status: str | None = None, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        rows = list(self.cases.values())
        if status:
            rows = [row for row in rows if row["case_status"] == status]
        if symbol:
            rows = [row for row in rows if row["canonical_symbol"] == symbol.upper()]
        return rows[:limit]

    def get_case(self, chart_case_id: str) -> dict[str, Any] | None:
        row = self.cases.get(chart_case_id)
        if row is None:
            return None
        return {
            **row,
            "labels": self.labels.get(chart_case_id, []),
            "reviews": self.reviews.get(chart_case_id, []),
            "library_members": self.members.get(chart_case_id, []),
            "label_tags": [],
        }

    def create_label(self, chart_case_id: str, payload: ManualLabelCreate) -> dict[str, Any]:
        case = self.get_case(chart_case_id)
        if case is None:
            raise ResearchRepositoryError("低谷图库样本不存在。")
        if payload.label_mode == "as_of" and payload.outcome_label:
            raise ResearchRepositoryError("当时可见模式不能填写结果标签。")
        tags = {row["tag_code"]: row for row in self.taxonomy}
        for tag in payload.tags:
            if tags[tag]["allowed_label_mode"] not in ("both", payload.label_mode):
                raise ResearchRepositoryError("当前标注模式不能使用事后复盘标签。")
        item = {**payload.model_dump(), "manual_label_id": payload.manual_label_id or "label_1", "chart_case_id": chart_case_id}
        self.labels.setdefault(chart_case_id, []).append(item)
        self.cases[chart_case_id]["case_status"] = "labeled"
        return item

    def create_review(self, chart_case_id: str, payload: ReviewCreate) -> dict[str, Any]:
        if self.get_case(chart_case_id) is None:
            raise ResearchRepositoryError("低谷图库样本不存在。")
        item = {**payload.model_dump(), "review_id": payload.review_id or "review_1", "chart_case_id": chart_case_id}
        self.reviews.setdefault(chart_case_id, []).append(item)
        if payload.review_status == "approved":
            self.cases[chart_case_id]["case_status"] = "approved"
        return item

    def create_library_member(self, chart_case_id: str, payload: LibraryMemberCreate) -> dict[str, Any]:
        if self.get_case(chart_case_id) is None:
            raise ResearchRepositoryError("低谷图库样本不存在。")
        item = {**payload.model_dump(), "library_member_id": payload.library_member_id or "member_1", "chart_case_id": chart_case_id}
        self.members.setdefault(chart_case_id, []).append(item)
        return item


def _client(monkeypatch) -> tuple[TestClient, MemoryResearchRepository]:  # noqa: ANN001
    repo = MemoryResearchRepository()
    monkeypatch.setattr(api_module, "get_repository", lambda: repo)
    return TestClient(app), repo


def test_readyz_declares_research_guardrails() -> None:
    body = TestClient(app).get("/readyz").json()

    assert body["service"] == "research-center-service"
    assert body["guardrails"]["direct_provider_calls_allowed"] is False
    assert body["guardrails"]["mutates_official_signals"] is False
    assert body["guardrails"]["manual_labels_are_research_assets"] is True


def test_valley_chart_case_label_review_and_library_flow(monkeypatch) -> None:  # noqa: ANN001
    client, repo = _client(monkeypatch)

    created = client.post(
        "/research/ambush/valley-chart/cases",
        json={
            "chart_case_id": "case_000759",
            "canonical_symbol": "000759.SZ",
            "stock_name": "中百集团",
            "case_trade_date": "2026-06-12",
            "case_source": "manual",
            "source_gap_codes": [],
            "dynamic_gap_codes": ["source_gap:dynamic_feature_bundle_missing"],
        },
    )
    assert created.status_code == 201
    assert created.json()["item"]["canonical_symbol"] == "000759.SZ"

    label = client.post(
        "/research/ambush/valley-chart/cases/case_000759/labels",
        json={
            "labeler_id": "tester",
            "label_mode": "as_of",
            "valley_structure_label": "低谷成熟",
            "tags": ["MATURE_VALLEY"],
        },
    )
    assert label.status_code == 201
    assert repo.cases["case_000759"]["case_status"] == "labeled"
    assert label.json()["guardrails"]["manual_label_mutates_official_signal"] is False

    review = client.post(
        "/research/ambush/valley-chart/cases/case_000759/reviews",
        json={
            "manual_label_id": label.json()["item"]["manual_label_id"],
            "reviewer_id": "reviewer",
            "review_status": "approved",
            "final_sample_role_label": "positive_prototype",
            "final_label_confidence": "high",
        },
    )
    assert review.status_code == 201

    member = client.post(
        "/research/ambush/valley-chart/cases/case_000759/library-members",
        json={
            "manual_label_id": label.json()["item"]["manual_label_id"],
            "library_role": "positive_prototype",
            "training_split": "review_only",
            "approved_by": "reviewer",
        },
    )
    assert member.status_code == 201
    assert member.json()["guardrails"]["mutates_model_parameters"] is False

    detail = client.get("/research/ambush/valley-chart/cases/case_000759").json()["item"]
    assert detail["case_status"] == "approved"
    assert len(detail["labels"]) == 1
    assert len(detail["reviews"]) == 1
    assert len(detail["library_members"]) == 1


def test_as_of_label_rejects_outcome_only_data(monkeypatch) -> None:  # noqa: ANN001
    client, _repo = _client(monkeypatch)
    client.post(
        "/research/ambush/valley-chart/cases",
        json={"chart_case_id": "case_1", "canonical_symbol": "000759.SZ", "case_trade_date": "2026-06-12"},
    )

    with_outcome = client.post(
        "/research/ambush/valley-chart/cases/case_1/labels",
        json={"labeler_id": "tester", "label_mode": "as_of", "outcome_label": "effective_turn_success"},
    )
    assert with_outcome.status_code == 409
    assert "当时可见模式" in with_outcome.json()["detail"]

    with_outcome_tag = client.post(
        "/research/ambush/valley-chart/cases/case_1/labels",
        json={"labeler_id": "tester", "label_mode": "as_of", "tags": ["FALSE_REBOUND"]},
    )
    assert with_outcome_tag.status_code == 409
    assert "事后复盘标签" in with_outcome_tag.json()["detail"]


def test_taxonomy_filter_keeps_frontend_taxonomy_driven(monkeypatch) -> None:  # noqa: ANN001
    client, _repo = _client(monkeypatch)

    as_of = client.get("/research/ambush/taxonomy?label_mode=as_of").json()
    assert as_of["guardrails"]["taxonomy_driven"] is True
    codes = {row["tag_code"] for row in as_of["items"]}
    assert codes == {"MATURE_VALLEY"}
