from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import data_inspector_service.repository as repository_module
from data_inspector_service.client import ServiceResult
from data_inspector_service.contracts import contracts_for_scope
from data_inspector_service.inspector import DataInspector
from data_inspector_service.repository import DataInspectorRepository
from data_inspector_service.schemas import InspectionRunCreate
from data_inspector_service.settings import Settings


class MemoryRepository(DataInspectorRepository):
    def __init__(self, counts: dict[str, int] | None = None) -> None:
        super().__init__(None)
        self.persisted = []
        self.counts = counts or {
            "source_adjusted_daily_bar_v1": 1,
            "governance_source_lineage_v1": 6,
            "decision_t_relay_day1_candidate_v1": 0,
            "decision_t_relay_day2_watch_snapshot_v1": 0,
            "decision_t_relay_day2_entry_trigger_v1": 0,
            "decision_t_relay_post_entry_monitor_v1": 0,
            "decision_t_relay_day3_exit_decision_v1": 0,
            "decision_t_relay_outcome_label_v1": 0,
            "decision_t_relay_game_hypothesis_snapshot_v1": 0,
            "research_t_relay_research_sample_v1": 0,
        }
        self.duplicate_summary = {"duplicate_group_count": 0, "duplicate_rows": [], "database_url_configured": False}

    def persist_run(self, run):  # noqa: ANN001
        run.run_id = len(self.persisted) + 1
        self.persisted.append(run)
        return run

    def source_table_counts(self) -> dict[str, int]:
        return dict(self.counts)

    def lineage_duplicate_summary(self, *, limit: int = 20) -> dict[str, Any]:
        return dict(self.duplicate_summary)


class FakeDbConnection:
    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.calls = calls

    def __enter__(self) -> "FakeDbConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def execute(self, query: str, params: dict[str, Any]) -> "FakeDbConnection":
        self.calls.append((query, params))
        return self

    def fetchone(self) -> dict[str, Any]:
        return {
            "run_id": 12,
            "scope": "core_closure",
            "as_of_trading_day": date(2026, 6, 12),
            "status": "ready",
        }


class FakeClient:
    def __init__(
        self,
        *,
        blocked_preflight: str | None = None,
        scheduler_ready: bool = True,
        blocked_research_task: str | None = None,
    ) -> None:
        self.blocked_preflight = blocked_preflight
        self.scheduler_ready = scheduler_ready
        self.blocked_research_task = blocked_research_task
        self.source_posts: list[tuple[str, dict[str, Any]]] = []
        self.scheduler_gets: list[str] = []
        self.scheduler_posts: list[tuple[str, dict[str, Any]]] = []
        self.model_gets: list[str] = []

    def get_source(self, path: str, *, params: dict[str, Any] | None = None) -> ServiceResult:
        if path == "/source/ops/production-readiness":
            return ServiceResult(
                ok=True,
                status_code=200,
                data={"status": "passed", "blocking_reasons": [], "warning_reasons": []},
            )
        if path == "/source/fetch/queues/summary":
            return ServiceResult(
                ok=True,
                status_code=200,
                data={"rows": [{"queue_name": "urgent_release_gate_queue", "queued_count": 0, "leased_count": 0, "dead_letter_count": 0}]},
            )
        if path == "/source/contracts":
            return ServiceResult(ok=True, status_code=200, data=[{"source_table_name": "source.adjusted_daily_bar_v1"}])
        raise AssertionError(path)

    def post_source(self, path: str, payload: dict[str, Any]) -> ServiceResult:
        self.source_posts.append((path, payload))
        blocked = payload["model_code"] == self.blocked_preflight
        return ServiceResult(
            ok=True,
            status_code=200,
            data={
                "can_release_official_signal": not blocked,
                "coverage_status": "blocked" if blocked else "passed",
                "freshness_status": "blocked" if blocked else "passed",
                "blocking_reasons": ["source.adjusted_daily_bar_v1.adjusted_close"] if blocked else [],
                "degraded_reasons": [],
                "repair_actions": [{"source_table_name": "source.adjusted_daily_bar_v1"}] if blocked else [],
            },
        )

    def get_scheduler(self, path: str, *, params: dict[str, Any] | None = None) -> ServiceResult:
        self.scheduler_gets.append(path)
        if path == "/scheduler/model-payload/requirements":
            return ServiceResult(
                ok=True,
                status_code=200,
                data={
                    "contract_kind": "scheduler_model_payload_requirements_v1",
                    "preflight_version": "scheduler_model_payload_preflight_v1",
                    "assembler_contract": "research_model_payload_assembler_v1",
                    "task_count": 2,
                    "tasks": [
                        {
                            "task_code": "hot.release_gate.preopen",
                            "task_kind": "release_gate",
                            "owner_service": "hot-candidates-service",
                            "official_publish": True,
                        },
                        {
                            "task_code": "t_relay.day1.scan.close",
                            "task_kind": "model_compute",
                            "owner_service": "t-board-relay-service",
                            "official_publish": False,
                        },
                    ],
                },
            )
        return ServiceResult(
            ok=self.scheduler_ready,
            status_code=200 if self.scheduler_ready else 503,
            data={"status": "ready" if self.scheduler_ready else "not_ready"},
        )

    def post_scheduler(self, path: str, payload: dict[str, Any]) -> ServiceResult:
        self.scheduler_posts.append((path, payload))
        task_code = str(payload["task_code"])
        blocked = task_code == self.blocked_research_task
        assembly_status = "blocked_data_gap" if blocked else "assembled_research_payload"
        gap_codes = ["source_gap:source_preflight_not_passed"] if blocked else []
        blocking_reasons = ["source.daily_bar_v1.close_price:000063.SZ:late"] if blocked else []
        return ServiceResult(
            ok=True,
            status_code=200,
            data={
                "contract_kind": "scheduler_research_payload_assemble_preflight_v1",
                "research_status_code": 200,
                "assembly": {
                    "payload_assembly_contract": "research_model_payload_assembler_v1",
                    "payload_assembly_status": assembly_status,
                    "payload_assembly_source": "research-service:research_model_payload_assembler_v1",
                    "task_code": task_code,
                    "owner_service": "hot-candidates-service" if task_code.startswith("hot.") else "t-board-relay-service",
                    "gap_codes": gap_codes,
                    "source_preflight": {
                        "can_release_official_signal": not blocked,
                        "coverage_status": "blocked" if blocked else "passed",
                        "freshness_status": "blocked" if blocked else "passed",
                        "blocking_reasons": blocking_reasons,
                    },
                    "payload": {
                        "source_gap_codes": gap_codes,
                        "contract_gaps": gap_codes,
                    },
                },
                "scheduler_preflight": {
                    "valid": not blocked,
                    "gap_codes": gap_codes,
                    "failure_codes": ["payload_assembly_status_not_ready"] if blocked else [],
                },
                "dispatch_allowed": not blocked,
                "owner_request_body_preview": None if blocked else {"payload": {"task_code": task_code}},
            },
        )

    def get_model_ready(self, model_code: str) -> ServiceResult:
        self.model_gets.append(model_code)
        return ServiceResult(ok=True, status_code=200, data={"status": "ready"})


def _settings(*, required_model_services: str | None = None) -> Settings:
    return Settings(
        source_data_service_base_url="http://source",
        scheduler_service_base_url="http://scheduler",
        hot_candidates_service_base_url="http://hot",
        candidate_memory_service_base_url="http://memory",
        ambush_watchlist_service_base_url="http://ambush",
        t_board_relay_service_base_url="http://tboard",
        data_inspector_required_model_services=required_model_services,
        default_trade_date="2026-06-12",
        default_symbol="000063.SZ",
        t_board_default_symbol="000759.SZ",
        persist_default=False,
    )


def test_latest_run_summary_filters_by_scope_and_trading_day(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_connect(database_url: str, *, row_factory):  # noqa: ANN001
        assert database_url == "postgresql://test"
        assert row_factory is repository_module.dict_row
        return FakeDbConnection(calls)

    monkeypatch.setattr(repository_module.psycopg, "connect", fake_connect)

    repo = DataInspectorRepository("postgresql://test")
    result = repo.latest_run_summary(scope="core_closure", as_of_trading_day=date(2026, 6, 12))

    assert result["run_id"] == 12
    query, params = calls[0]
    assert "where scope = %(scope)s and as_of_trading_day = %(as_of_trading_day)s" in query
    assert "order by started_at desc, run_id desc limit 1" in query
    assert params == {"scope": "core_closure", "as_of_trading_day": date(2026, 6, 12)}


def test_startup_guard_is_source_first_and_does_not_call_scheduler() -> None:
    client = FakeClient()
    inspector = DataInspector(settings=_settings(), repository=MemoryRepository(), client=client)  # type: ignore[arg-type]

    run = inspector.build_inspection(InspectionRunCreate(scope="startup_guard", persist=False))

    assert run.status == "ready"
    assert run.p0_gap_count == 0
    assert len(client.source_posts) == 5
    assert client.scheduler_gets == []
    assert client.model_gets == []
    t_board_posts = [payload for _, payload in client.source_posts if payload["model_code"] == "t_board_relay"]
    assert {payload["model_phase"] for payload in t_board_posts} == {"day1_scan", "day2_trigger"}
    assert all(payload["symbols"] == ["000759.SZ"] for payload in t_board_posts)
    assert "source_production_readiness" in run.subjects[0].summary["observed_domains"]
    assert "source_lineage_presence" in run.subjects[0].summary["observed_domains"]


def test_core_closure_checks_scheduler_models_preflight_and_lineage() -> None:
    client = FakeClient()
    repo = MemoryRepository()
    inspector = DataInspector(settings=_settings(), repository=repo, client=client)  # type: ignore[arg-type]

    run = inspector.build_inspection(
        InspectionRunCreate(scope="core_closure", as_of_trading_day=date(2026, 6, 12), persist=True)
    )

    assert run.run_id == 1
    assert run.status == "ready"
    assert run.p0_gap_count == 0
    assert len(client.source_posts) == 5
    assert client.scheduler_gets == ["/readyz"]
    assert client.model_gets == ["hot_candidates", "candidate_memory", "ambush_watchlist", "t_board_relay"]
    observed = set(run.subjects[0].summary["observed_domains"])
    for contract in contracts_for_scope("core_closure"):
        assert contract.domain_code in observed


def test_core_closure_observes_policy_disabled_models_without_readyz_gap() -> None:
    client = FakeClient()
    repo = MemoryRepository()
    inspector = DataInspector(
        settings=_settings(required_model_services="none"),
        repository=repo,
        client=client,
    )  # type: ignore[arg-type]

    run = inspector.build_inspection(
        InspectionRunCreate(scope="core_closure", as_of_trading_day=date(2026, 6, 12), persist=False)
    )

    assert run.status == "ready"
    assert run.p0_gap_count == 0
    assert client.model_gets == []
    observed = set(run.subjects[0].summary["observed_domains"])
    for contract in contracts_for_scope("core_closure"):
        assert contract.domain_code in observed
    runtime_services = run.subjects[0].summary["diagnostics"]["runtime_services"]
    assert runtime_services["model_availability_policy"]["disabled_model_codes"] == [
        "hot_candidates",
        "candidate_memory",
        "ambush_watchlist",
        "t_board_relay",
    ]
    assert runtime_services["hot_candidates_model_ready"]["data"]["status"] == "disabled_by_policy"


def test_core_closure_checks_only_required_models_under_policy() -> None:
    client = FakeClient()
    repo = MemoryRepository()
    inspector = DataInspector(
        settings=_settings(required_model_services="t_board_relay"),
        repository=repo,
        client=client,
    )  # type: ignore[arg-type]

    run = inspector.build_inspection(
        InspectionRunCreate(scope="core_closure", as_of_trading_day=date(2026, 6, 12), persist=False)
    )

    assert run.status == "ready"
    assert client.model_gets == ["t_board_relay"]
    runtime_services = run.subjects[0].summary["diagnostics"]["runtime_services"]
    assert runtime_services["hot_candidates_model_ready"]["data"]["status"] == "disabled_by_policy"
    assert runtime_services["t_board_relay_model_ready"]["data"]["status"] == "ready"


def test_blocked_preflight_generates_p0_gap_and_source_repair_task() -> None:
    client = FakeClient(blocked_preflight="candidate_memory")
    inspector = DataInspector(settings=_settings(), repository=MemoryRepository(), client=client)  # type: ignore[arg-type]

    run = inspector.build_inspection(
        InspectionRunCreate(scope="source_release_gate", symbols=["000063.SZ"], persist=False)
    )

    assert run.status == "blocked"
    assert run.p0_gap_count == 1
    gap = run.gaps[0]
    assert gap.domain_code == "candidate_memory_release_preflight"
    assert gap.blocks_publish is True
    assert gap.details["blocking_reasons"] == ["source.adjusted_daily_bar_v1.adjusted_close"]
    assert run.remediation_tasks[0].owner_service == "source-data-service"
    assert run.remediation_tasks[0].action_type == "repair_source_release_preflight"


def test_source_release_gate_observes_all_contract_domains() -> None:
    client = FakeClient()
    inspector = DataInspector(settings=_settings(), repository=MemoryRepository(), client=client)  # type: ignore[arg-type]

    run = inspector.build_inspection(
        InspectionRunCreate(scope="source_release_gate", symbols=["000063.SZ"], persist=False)
    )

    observed = set(run.subjects[0].summary["observed_domains"])
    assert run.status == "ready"
    assert run.publish_due_missing_domain_count == 0
    for contract in contracts_for_scope("source_release_gate"):
        assert contract.domain_code in observed


def test_lineage_duplicate_observation_is_non_blocking_warning() -> None:
    client = FakeClient()
    repo = MemoryRepository()
    repo.duplicate_summary = {
        "duplicate_group_count": 2,
        "duplicate_rows": [
            {
                "source_table_name": "source.adjusted_daily_bar_v1",
                "source_pk": "000063.SZ|2026-06-12",
                "canonical_field_name": "adjusted_close",
                "duplicate_count": 2,
            }
        ],
        "database_url_configured": True,
    }
    inspector = DataInspector(settings=_settings(), repository=repo, client=client)  # type: ignore[arg-type]

    run = inspector.build_inspection(InspectionRunCreate(scope="core_closure", persist=False))

    assert run.status == "ready"
    assert run.gap_count == 0
    assert run.warning_codes == ["source_lineage_duplicate_observed:2"]
    duplicate_summary = run.subjects[0].summary["diagnostics"]["source_lineage"]["duplicate_summary"]
    assert duplicate_summary["duplicate_group_count"] == 2


def test_research_payload_assembly_scope_uses_scheduler_preflight_without_owner_dispatch() -> None:
    client = FakeClient()
    inspector = DataInspector(settings=_settings(), repository=MemoryRepository(), client=client)  # type: ignore[arg-type]

    run = inspector.build_inspection(
        InspectionRunCreate(
            scope="research_payload_assembly",
            as_of_trading_day=date(2026, 6, 12),
            as_of_time=datetime(2026, 6, 18, 0, 40, tzinfo=timezone.utc),
            symbols=["000063.SZ"],
            persist=False,
        )
    )

    assert run.status == "ready"
    assert run.gap_count == 0
    assert client.scheduler_gets == ["/scheduler/model-payload/requirements"]
    assert [path for path, _ in client.scheduler_posts] == [
        "/scheduler/model-payload/assemble-preflight",
        "/scheduler/model-payload/assemble-preflight",
    ]
    assert all(payload["persist_audit"] is False for _, payload in client.scheduler_posts)
    assert client.model_gets == []
    observed = set(run.subjects[0].summary["observed_domains"])
    assert "research_payload_assembly" in observed
    diagnostics = run.subjects[0].summary["diagnostics"]["research_payload_assembly"]
    assert diagnostics["summary"]["assembled_count"] == 2
    t_relay_payload = client.scheduler_posts[1][1]
    assert t_relay_payload["symbols"] == ["000759.SZ"]


def test_research_payload_assembly_blocked_gap_keeps_source_reasons() -> None:
    client = FakeClient(blocked_research_task="hot.release_gate.preopen")
    inspector = DataInspector(settings=_settings(), repository=MemoryRepository(), client=client)  # type: ignore[arg-type]

    run = inspector.build_inspection(
        InspectionRunCreate(
            scope="research_payload_assembly",
            as_of_trading_day=date(2026, 6, 12),
            as_of_time=datetime(2026, 6, 12, 7, 5, tzinfo=timezone.utc),
            symbols=["000063.SZ"],
            persist=False,
        )
    )

    assert run.status == "blocked"
    assert run.p0_gap_count == 1
    gap = run.gaps[0]
    assert gap.domain_code == "research_payload_assembly"
    assert gap.gap_type == "research_payload_assembly_blocked"
    assert gap.severity == "P0"
    assert gap.blocks_publish is True
    assert gap.details["task_code"] == "hot.release_gate.preopen"
    assert "source_gap:source_preflight_not_passed" in gap.details["gap_codes"]
    assert gap.details["blocking_reasons"] == ["source.daily_bar_v1.close_price:000063.SZ:late"]
    remediation = run.remediation_tasks[0]
    assert remediation.owner_service == "source-data-service"
    assert remediation.action_type == "repair_research_payload_source_gap"
    assert remediation.request_payload["must_use_fetch_orchestration"] is True
