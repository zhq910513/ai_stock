from __future__ import annotations

from research_service.assembler import ResearchPayloadAssembler
from research_service.executor import ResearchModelExecutor
from research_service.materializer import ResearchDecisionMaterializer
from research_service.owner_client import ModelOwnerClient
from research_service.repository import ResearchPayloadRepository
from research_service.settings import get_settings
from research_service.source_client import HttpSourceDataClient

settings = get_settings()


def build_repository() -> ResearchPayloadRepository:
    return ResearchPayloadRepository(settings.effective_database_url)


def build_assembler() -> ResearchPayloadAssembler:
    return ResearchPayloadAssembler(
        repository=build_repository(),
        source_client=HttpSourceDataClient(settings.source_data_service_base_url, settings.request_timeout_seconds),
        settings=settings,
    )


def build_executor() -> ResearchModelExecutor:
    repository = build_repository()
    assembler = ResearchPayloadAssembler(
        repository=repository,
        source_client=HttpSourceDataClient(settings.source_data_service_base_url, settings.request_timeout_seconds),
        settings=settings,
    )
    return ResearchModelExecutor(
        assembler=assembler,
        repository=repository,
        owner_client=ModelOwnerClient(
            hot_candidates_base_url=settings.hot_candidates_service_base_url,
            candidate_memory_base_url=settings.candidate_memory_service_base_url,
            ambush_watchlist_base_url=settings.ambush_watchlist_service_base_url,
            t_board_relay_base_url=settings.t_board_relay_service_base_url,
            request_timeout_seconds=settings.request_timeout_seconds,
        ),
        materializer=ResearchDecisionMaterializer(repository),
    )
